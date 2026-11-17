import asyncio
import logging
from datetime import UTC, datetime, timedelta

from sqlalchemy import select, update
from sqlalchemy.ext.asyncio import AsyncSession

from .db import SessionLocal
from .ingestion.pipeline import IngestionError, process_document
from .models import Document, DocumentStatus, IngestionJob, JobStatus

logger = logging.getLogger(__name__)

MAX_ATTEMPTS = 3
LEASE = timedelta(minutes=10)


async def requeue_stale_jobs() -> int:
    """Return jobs whose worker lease expired to the queue.

    Covers Render free-tier sleep/wake and crashed workers.
    """
    async with SessionLocal() as db:
        result = await db.execute(
            update(IngestionJob)
            .where(
                IngestionJob.status == JobStatus.running,
                IngestionJob.lease_expires_at.is_not(None),
                IngestionJob.lease_expires_at < datetime.now(UTC),
            )
            .values(status=JobStatus.queued, lease_expires_at=None, heartbeat_at=None)
        )
        await db.commit()
        count = result.rowcount or 0
        if count:
            logger.info("Requeued %s stale ingestion job(s)", count)
        return count


async def _claim_job(db: AsyncSession) -> IngestionJob | None:
    now = datetime.now(UTC)
    job = await db.scalar(
        select(IngestionJob)
        .where(IngestionJob.status == JobStatus.queued)
        .order_by(IngestionJob.created_at)
        .limit(1)
        .with_for_update(skip_locked=True)
    )
    if job is None:
        return None

    job.status = JobStatus.running
    job.attempts += 1
    job.started_at = job.started_at or now
    job.lease_expires_at = now + LEASE
    job.heartbeat_at = now

    document = await db.get(Document, job.document_id)
    if document is not None:
        document.status = DocumentStatus.processing
        document.failure_reason = None
    return job


async def _fail_or_retry(job_id, attempts: int, error: IngestionError) -> None:
    async with SessionLocal() as db:
        job = await db.get(IngestionJob, job_id)
        if job is None:
            return
        job.error_code = error.__class__.__name__
        job.heartbeat_at = datetime.now(UTC)

        document = await db.get(Document, job.document_id)
        if attempts >= MAX_ATTEMPTS:
            job.status = JobStatus.failed
            job.completed_at = datetime.now(UTC)
            job.lease_expires_at = None
            if document is not None:
                document.status = DocumentStatus.failed
                document.failure_reason = str(error)
        else:
            job.status = JobStatus.queued
            job.lease_expires_at = None
            if document is not None:
                document.status = DocumentStatus.queued
        await db.commit()


async def process_one() -> bool:
    async with SessionLocal() as db:
        async with db.begin():
            job = await _claim_job(db)
            if job is None:
                return False
            job_id = job.id
            document_id = job.document_id
            attempts = job.attempts

    try:
        await process_document(document_id, job_id)
    except IngestionError as exc:
        logger.warning("Ingestion failed for document %s: %s", document_id, exc)
        await _fail_or_retry(job_id, attempts, exc)
    except Exception as exc:
        logger.exception("Unexpected ingestion failure for document %s", document_id)
        await _fail_or_retry(
            job_id,
            attempts,
            IngestionError("Processing failed. Please try again."),
        )
        del exc
    return True


async def run_worker(stop_event: asyncio.Event) -> None:
    await requeue_stale_jobs()
    logger.info("Ingestion worker started")
    while not stop_event.is_set():
        try:
            processed = await process_one()
        except Exception:
            logger.exception("Worker loop error")
            processed = False

        timeout = 0.5 if processed else 8
        try:
            await asyncio.wait_for(stop_event.wait(), timeout=timeout)
        except TimeoutError:
            pass
    logger.info("Ingestion worker stopped")
