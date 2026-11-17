from __future__ import annotations

import logging
import uuid
from datetime import UTC, datetime, timedelta

from sqlalchemy import delete, select

from ..config import get_settings
from ..db import SessionLocal
from ..models import (
    AssetKind,
    Document,
    DocumentAsset,
    DocumentChunk,
    DocumentStatus,
    IngestionJob,
    JobStatus,
)
from ..providers.embeddings import EmbeddingError, get_embeddings
from ..storage import get_storage
from .assets import AssetData, caption_assets, extract_page_assets
from .chunking import PdfExtractionError, build_sections, chunk_sections, extract_pages

logger = logging.getLogger(__name__)

EMBED_BATCH_SIZE = 32
LEASE = timedelta(minutes=10)


class IngestionError(RuntimeError):
    """Error with a message safe to show to the user."""


async def _set_stage(job_id: uuid.UUID, stage: str) -> None:
    now = datetime.now(UTC)
    async with SessionLocal() as db:
        job = await db.get(IngestionJob, job_id)
        if job is None:
            return
        job.last_stage = stage
        job.heartbeat_at = now
        job.lease_expires_at = now + LEASE
        await db.commit()


async def _finish_job(
    job_id: uuid.UUID,
    *,
    document_status: DocumentStatus,
    job_status: JobStatus = JobStatus.completed,
    page_count: int | None = None,
    failure_reason: str | None = None,
) -> None:
    now = datetime.now(UTC)
    async with SessionLocal() as db:
        job = await db.get(IngestionJob, job_id)
        if job is None:
            return
        job.status = job_status
        job.completed_at = now
        job.lease_expires_at = None
        job.heartbeat_at = now

        document = await db.get(Document, job.document_id)
        if document is not None:
            document.status = document_status
            document.failure_reason = failure_reason
            if page_count is not None:
                document.page_count = page_count
            if document_status == DocumentStatus.ready:
                document.processed_at = now
        await db.commit()


async def _clear_outputs(document_id: uuid.UUID) -> None:
    """Remove previous chunks, assets, and stored asset files before a retry."""
    async with SessionLocal() as db:
        assets = (
            await db.scalars(select(DocumentAsset).where(DocumentAsset.document_id == document_id))
        ).all()
        storage_keys = [asset.storage_key for asset in assets]
        await db.execute(delete(DocumentChunk).where(DocumentChunk.document_id == document_id))
        await db.execute(delete(DocumentAsset).where(DocumentAsset.document_id == document_id))
        await db.commit()

    storage = get_storage()
    for key in storage_keys:
        try:
            await storage.delete(key)
        except Exception:
            logger.warning("Could not delete stale asset %s", key, exc_info=True)


async def _store_assets(
    assets: list[AssetData], document_id: uuid.UUID, user_id: uuid.UUID
) -> dict[int, str]:
    storage = get_storage()
    rows: list[DocumentAsset] = []

    for asset in assets:
        storage_key = (
            f"documents/{user_id}/assets/{document_id}/"
            f"{asset.kind.value}-p{asset.page_number}-{asset.asset_index}.{asset.extension}"
        )
        try:
            await storage.save_bytes(storage_key, asset.data)
        except Exception:
            logger.exception(
                "Could not store %s asset for page %s of document %s",
                asset.kind,
                asset.page_number,
                document_id,
            )
            continue

        rows.append(
            DocumentAsset(
                document_id=document_id,
                user_id=user_id,
                page_number=asset.page_number,
                kind=asset.kind,
                asset_index=asset.asset_index,
                storage_key=storage_key,
                mime_type=asset.mime_type,
                width=asset.width,
                height=asset.height,
                caption=asset.caption,
            )
        )

    if rows:
        async with SessionLocal() as db:
            db.add_all(rows)
            await db.commit()

    figure_text_by_page: dict[int, list[str]] = {}
    for asset in assets:
        if not asset.caption:
            continue
        prefix = "Figure" if asset.kind == AssetKind.figure else "Page visual"
        figure_text_by_page.setdefault(asset.page_number, []).append(
            f"{prefix} on page {asset.page_number}: {asset.caption}"
        )

    return {page: "\n".join(captions) for page, captions in figure_text_by_page.items()}


async def process_document(document_id: uuid.UUID, job_id: uuid.UUID) -> None:
    settings = get_settings()

    async with SessionLocal() as db:
        document = await db.get(Document, document_id)
        if document is None:
            return
        storage_key = document.storage_key
        user_id = document.user_id

    await _set_stage(job_id, "downloading")
    data = await get_storage().read_bytes(storage_key)

    await _set_stage(job_id, "extracting")
    try:
        extraction = extract_pages(
            data,
            settings.max_pages,
            ocr_enabled=settings.ocr_enabled,
            ocr_language=settings.ocr_language,
            ocr_dpi=settings.ocr_dpi,
        )
    except PdfExtractionError as exc:
        raise IngestionError(str(exc)) from exc

    ocr_text_by_page = {
        page.page_number: page.text
        for page in extraction.pages
        if page.page_number in set(extraction.ocr_pages)
    }

    if extraction.needs_ocr:
        await _finish_job(
            job_id,
            document_status=DocumentStatus.needs_ocr,
            page_count=extraction.page_count,
            failure_reason=(
                "No readable text found. This PDF appears to be scanned; "
                "OCR could not extract usable text."
            ),
        )
        return

    await _set_stage(job_id, "extracting figures")
    try:
        assets, visual_pages = extract_page_assets(data)
    except Exception:
        logger.exception("Figure extraction failed for document %s", document_id)
        assets, visual_pages = [], set()

    captions = 0
    if assets:
        await _set_stage(job_id, "captioning figures")
        try:
            captions = await caption_assets(assets, settings.max_figure_captions)
        except Exception:
            logger.exception("Figure captioning failed for document %s", document_id)

    await _clear_outputs(document_id)
    figure_text_by_page = await _store_assets(assets, document_id, user_id) if assets else {}

    await _set_stage(job_id, "chunking")
    sections = build_sections(data, extra_text_by_page=ocr_text_by_page)
    chunks = chunk_sections(
        sections,
        figure_text_by_page=figure_text_by_page,
        target_tokens=settings.chunk_target_tokens,
        overlap_tokens=settings.chunk_overlap_tokens,
    )
    if not chunks:
        await _finish_job(
            job_id,
            document_status=DocumentStatus.needs_ocr,
            page_count=extraction.page_count,
            failure_reason="No readable text could be extracted from this PDF.",
        )
        return

    await _set_stage(job_id, "embedding")
    provider = get_embeddings()
    try:
        for start in range(0, len(chunks), EMBED_BATCH_SIZE):
            batch = chunks[start : start + EMBED_BATCH_SIZE]
            embedding_inputs = [
                chunk.text
                + (f"\n\nFigure context:\n{chunk.figure_text}" if chunk.figure_text else "")
                for chunk in batch
            ]
            vectors = await provider.embed_documents(embedding_inputs)
            async with SessionLocal() as db:
                db.add_all(
                    [
                        DocumentChunk(
                            document_id=document_id,
                            user_id=user_id,
                            chunk_index=chunk.index,
                            text=chunk.text,
                            page_start=chunk.page_start,
                            page_end=chunk.page_end,
                            section_title=chunk.section_title,
                            token_count=chunk.token_count,
                            figure_text=chunk.figure_text,
                            embedding=vector,
                            embedding_model=provider.model_id,
                        )
                        for chunk, vector in zip(batch, vectors, strict=True)
                    ]
                )
                await db.commit()
            await _set_stage(job_id, f"embedding {start + len(batch)}/{len(chunks)}")
    except EmbeddingError as exc:
        raise IngestionError(
            "Search indexing failed because the embedding provider is unavailable."
        ) from exc

    await _finish_job(
        job_id,
        document_status=DocumentStatus.ready,
        page_count=extraction.page_count,
    )
    logger.info(
        "Document %s indexed: %s pages, %s OCR pages, %s chunks, %s assets, "
        "%s visual pages, %s captions",
        document_id,
        extraction.page_count,
        len(extraction.ocr_pages),
        len(chunks),
        len(assets),
        len(visual_pages),
        captions,
    )
