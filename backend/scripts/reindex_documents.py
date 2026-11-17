"""Queue documents for full re-indexing.

Use after changing the embedding provider/model, chunk settings, OCR, or figure
captioning. Re-indexing replaces chunks and stored page/figure assets.

Usage:
    cd backend
    uv run python scripts/reindex_documents.py --all
    uv run python scripts/reindex_documents.py --document-id <uuid>
"""

import argparse
import asyncio
import uuid

from sqlalchemy import select

from studbud_backend.db import SessionLocal
from studbud_backend.models import Document, DocumentStatus, IngestionJob, JobStatus


async def main(args: argparse.Namespace) -> int:
    async with SessionLocal() as db:
        statement = select(Document)
        if args.document_id:
            statement = statement.where(Document.id == uuid.UUID(args.document_id))
        elif args.user_id:
            statement = statement.where(Document.user_id == uuid.UUID(args.user_id))
        documents = (await db.scalars(statement)).all()

        if not documents:
            print("No documents matched.")
            return 1

        for document in documents:
            document.status = DocumentStatus.queued
            document.failure_reason = None
            db.add(
                IngestionJob(
                    document_id=document.id,
                    status=JobStatus.queued,
                    last_stage="reindex",
                )
            )
            print(f"Queued {document.id} {document.file_name}")
        await db.commit()

    print("Worker will pick these up. Re-indexing replaces prior chunks and assets.")
    return 0


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    group = parser.add_mutually_exclusive_group(required=True)
    group.add_argument("--all", action="store_true")
    group.add_argument("--document-id")
    group.add_argument("--user-id")
    parsed = parser.parse_args()
    raise SystemExit(asyncio.run(main(parsed)))
