from __future__ import annotations

import uuid
from datetime import UTC, datetime

from fastapi import HTTPException, status
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from .config import get_settings
from .models import Document, Explanation


def _day_start() -> datetime:
    now = datetime.now(UTC)
    return now.replace(hour=0, minute=0, second=0, microsecond=0)


async def enforce_upload_quota(
    db: AsyncSession,
    user_id: uuid.UUID,
    incoming_bytes: int,
    incoming_pages: int,
) -> None:
    settings = get_settings()

    document_count = (
        await db.scalar(
            select(func.count()).select_from(Document).where(Document.user_id == user_id)
        )
        or 0
    )
    if document_count >= settings.user_max_documents:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail=(
                f"Library limit reached: {settings.user_max_documents} documents. "
                "Delete a document before uploading another."
            ),
        )

    total_bytes, total_pages = (
        await db.execute(
            select(
                func.coalesce(func.sum(Document.file_size_bytes), 0),
                func.coalesce(func.sum(Document.page_count), 0),
            ).where(Document.user_id == user_id)
        )
    ).one()

    storage_limit = settings.user_max_storage_mb * 1024 * 1024
    if int(total_bytes) + incoming_bytes > storage_limit:
        raise HTTPException(
            status_code=status.HTTP_413_CONTENT_TOO_LARGE,
            detail=(
                f"Storage quota reached: {settings.user_max_storage_mb} MB per user. "
                "Delete a document or request a larger quota."
            ),
        )

    if int(total_pages) + incoming_pages > settings.user_max_pages:
        raise HTTPException(
            status_code=status.HTTP_413_CONTENT_TOO_LARGE,
            detail=(
                f"Page quota reached: {settings.user_max_pages} pages per user. "
                "Delete a document or request a larger quota."
            ),
        )

    uploads_today = (
        await db.scalar(
            select(func.count())
            .select_from(Document)
            .where(Document.user_id == user_id, Document.created_at >= _day_start())
        )
        or 0
    )
    if uploads_today >= settings.user_daily_uploads:
        raise HTTPException(
            status_code=status.HTTP_429_TOO_MANY_REQUESTS,
            detail=(
                f"Daily upload limit reached ({settings.user_daily_uploads}). Try again tomorrow."
            ),
        )


async def enforce_explanation_quota(db: AsyncSession, user_id: uuid.UUID) -> None:
    settings = get_settings()
    count = (
        await db.scalar(
            select(func.count())
            .select_from(Explanation)
            .where(Explanation.user_id == user_id, Explanation.created_at >= _day_start())
        )
        or 0
    )
    if count >= settings.user_daily_explanations:
        raise HTTPException(
            status_code=status.HTTP_429_TOO_MANY_REQUESTS,
            detail=(
                f"Daily explanation limit reached ({settings.user_daily_explanations}). "
                "Try again tomorrow."
            ),
        )
