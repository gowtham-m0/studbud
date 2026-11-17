from __future__ import annotations

import logging
import os
import tempfile
import uuid
from pathlib import Path

import pymupdf as fitz
from fastapi import APIRouter, Depends, File, HTTPException, Query, Request, UploadFile, status
from fastapi.responses import Response
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from ..config import get_settings
from ..db import get_db
from ..deps import get_current_user
from ..models import (
    Document,
    DocumentAsset,
    DocumentStatus,
    IngestionJob,
    JobStatus,
    User,
)
from ..quotas import enforce_upload_quota
from ..rate_limit import enforce_rate_limit
from ..schemas import DocumentAssetOut, DocumentOut, UploadResponse
from ..storage import get_storage

logger = logging.getLogger(__name__)
router = APIRouter(prefix="/api/documents", tags=["documents"])


def _safe_filename(name: str | None) -> str:
    base = Path(name or "document.pdf").name
    cleaned = "".join(ch for ch in base if ch.isalnum() or ch in " ._-()").strip()
    cleaned = cleaned or "document.pdf"
    if not cleaned.lower().endswith(".pdf"):
        cleaned += ".pdf"
    return cleaned[:255]


async def _owned_document(document_id: uuid.UUID, user: User, db: AsyncSession) -> Document:
    document = await db.scalar(
        select(Document).where(Document.id == document_id, Document.user_id == user.id)
    )
    if document is None:
        raise HTTPException(status_code=404, detail="Document not found.")
    return document


@router.post(
    "",
    response_model=UploadResponse,
    status_code=status.HTTP_202_ACCEPTED,
)
async def upload_document(
    request: Request,
    file: UploadFile = File(...),
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> UploadResponse:
    settings = get_settings()
    await enforce_rate_limit(request, "upload", 20, window_seconds=3600)

    if file.content_type not in {"application/pdf", "application/octet-stream"}:
        raise HTTPException(status_code=415, detail="Only PDF files are supported.")

    max_bytes = settings.max_upload_mb * 1024 * 1024
    temp_path: Path | None = None
    size = 0
    header = b""

    try:
        with tempfile.NamedTemporaryFile(delete=False, suffix=".pdf") as temp:
            temp_path = Path(temp.name)
            while chunk := await file.read(1024 * 1024):
                size += len(chunk)
                if size > max_bytes:
                    raise HTTPException(
                        status_code=413,
                        detail=f"File is larger than {settings.max_upload_mb} MB.",
                    )
                if len(header) < 5:
                    header += chunk[: 5 - len(header)]
                temp.write(chunk)
            temp.flush()
            os.fsync(temp.fileno())

        if header != b"%PDF-":
            raise HTTPException(status_code=422, detail="File is not a valid PDF.")

        try:
            pdf = fitz.open(temp_path)
            if pdf.needs_pass:
                raise HTTPException(status_code=422, detail="Encrypted PDFs are not supported.")
            page_count = pdf.page_count
            pdf.close()
        except HTTPException:
            raise
        except Exception as exc:
            raise HTTPException(status_code=422, detail="File is not a valid PDF.") from exc

        if page_count == 0:
            raise HTTPException(status_code=422, detail="The PDF has no pages.")
        if page_count > settings.max_pages:
            raise HTTPException(
                status_code=422,
                detail=f"The PDF has {page_count} pages; the limit is {settings.max_pages}.",
            )

        await enforce_upload_quota(db, user.id, size, page_count)

        filename = _safe_filename(file.filename)
        storage_key = f"documents/{user.id}/{uuid.uuid4().hex}.pdf"
        await get_storage().save(storage_key, temp_path)

        document = Document(
            user_id=user.id,
            file_name=filename,
            storage_key=storage_key,
            mime_type="application/pdf",
            file_size_bytes=size,
            page_count=page_count,
            status=DocumentStatus.queued,
        )
        db.add(document)
        await db.flush()
        db.add(
            IngestionJob(
                document_id=document.id,
                status=JobStatus.queued,
                last_stage="uploaded",
            )
        )
        await db.commit()
        await db.refresh(document)

        return UploadResponse(
            document_id=document.id,
            status=document.status,
            message="Your document is queued for processing.",
        )
    finally:
        await file.close()
        if temp_path is not None:
            temp_path.unlink(missing_ok=True)


@router.get("", response_model=list[DocumentOut])
async def list_documents(
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> list[Document]:
    documents = (
        await db.scalars(
            select(Document).where(Document.user_id == user.id).order_by(Document.created_at.desc())
        )
    ).all()
    return list(documents)


@router.get("/{document_id}", response_model=DocumentOut)
async def get_document(
    document_id: uuid.UUID,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> Document:
    return await _owned_document(document_id, user, db)


@router.delete("/{document_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_document(
    document_id: uuid.UUID,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> None:
    document = await _owned_document(document_id, user, db)
    storage_key = document.storage_key
    asset_prefix = f"documents/{document.user_id}/assets/{document.id}/"
    file_name = document.file_name

    await db.delete(document)
    await db.commit()

    storage = get_storage()
    try:
        await storage.delete(storage_key)
    except Exception:
        logger.exception(
            "Failed to delete original file %s for document %s (%s)",
            storage_key,
            document_id,
            file_name,
        )
    try:
        await storage.delete_prefix(asset_prefix)
    except Exception:
        logger.exception(
            "Failed to delete asset prefix %s for document %s (%s)",
            asset_prefix,
            document_id,
            file_name,
        )


@router.post(
    "/{document_id}/retry",
    response_model=DocumentOut,
    status_code=status.HTTP_202_ACCEPTED,
)
async def retry_document(
    document_id: uuid.UUID,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> Document:
    document = await _owned_document(document_id, user, db)
    if document.status not in {DocumentStatus.failed, DocumentStatus.needs_ocr}:
        raise HTTPException(
            status_code=409,
            detail="Only failed or scanned documents can be retried.",
        )

    document.status = DocumentStatus.queued
    document.failure_reason = None
    db.add(IngestionJob(document_id=document.id, status=JobStatus.queued, last_stage="retry"))
    await db.commit()
    await db.refresh(document)
    return document


@router.get("/{document_id}/assets", response_model=list[DocumentAssetOut])
async def list_document_assets(
    document_id: uuid.UUID,
    page: int | None = Query(default=None, ge=1),
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> list[DocumentAssetOut]:
    await _owned_document(document_id, user, db)

    statement = select(DocumentAsset).where(
        DocumentAsset.document_id == document_id,
        DocumentAsset.user_id == user.id,
    )
    if page is not None:
        statement = statement.where(DocumentAsset.page_number == page)
    statement = statement.order_by(DocumentAsset.page_number, DocumentAsset.asset_index)
    assets = (await db.scalars(statement)).all()

    return [
        DocumentAssetOut(
            id=asset.id,
            page_number=asset.page_number,
            kind=asset.kind,
            asset_index=asset.asset_index,
            mime_type=asset.mime_type,
            width=asset.width,
            height=asset.height,
            caption=asset.caption,
            content_path=f"/api/documents/{document_id}/assets/{asset.id}/content",
        )
        for asset in assets
    ]


@router.get("/{document_id}/assets/{asset_id}/content")
async def get_document_asset_content(
    document_id: uuid.UUID,
    asset_id: uuid.UUID,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> Response:
    asset = await db.scalar(
        select(DocumentAsset).where(
            DocumentAsset.id == asset_id,
            DocumentAsset.document_id == document_id,
            DocumentAsset.user_id == user.id,
        )
    )
    if asset is None:
        raise HTTPException(status_code=404, detail="Figure not found.")

    try:
        data = await get_storage().read_bytes(asset.storage_key)
    except Exception as exc:
        logger.exception("Failed to read asset %s", asset_id)
        raise HTTPException(status_code=404, detail="Figure file not found.") from exc

    return Response(
        content=data,
        media_type=asset.mime_type,
        headers={"Cache-Control": "private, max-age=300"},
    )


@router.get("/{document_id}/file")
async def get_document_file(
    document_id: uuid.UUID,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> Response:
    document = await _owned_document(document_id, user, db)
    try:
        data = await get_storage().read_bytes(document.storage_key)
    except Exception as exc:
        logger.exception("Failed to read stored file for document %s", document_id)
        raise HTTPException(status_code=404, detail="Stored file not found.") from exc

    safe_ascii = document.file_name.encode("ascii", "ignore").decode("ascii") or "document.pdf"
    return Response(
        content=data,
        media_type="application/pdf",
        headers={
            "Content-Disposition": f'inline; filename="{safe_ascii}"',
            "Cache-Control": "private, max-age=60",
        },
    )
