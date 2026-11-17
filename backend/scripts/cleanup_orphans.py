"""Delete storage objects not referenced by a document or asset row.

Dry run:
    cd backend
    uv run python scripts/cleanup_orphans.py

Delete:
    uv run python scripts/cleanup_orphans.py --apply
"""

import argparse
import asyncio

from sqlalchemy import select

from studbud_backend.db import SessionLocal
from studbud_backend.models import Document, DocumentAsset
from studbud_backend.storage import get_storage


async def main(apply: bool) -> int:
    storage = get_storage()

    async with SessionLocal() as db:
        document_keys = set((await db.scalars(select(Document.storage_key))).all())
        asset_keys = set((await db.scalars(select(DocumentAsset.storage_key))).all())

    known = document_keys | asset_keys
    stored = set(await storage.list_keys("documents/"))
    orphans = sorted(stored - known)

    print(f"Stored objects: {len(stored)}")
    print(f"Referenced objects: {len(known)}")
    print(f"Orphan objects: {len(orphans)}")

    if not apply:
        for key in orphans[:20]:
            print(f"  {key}")
        if len(orphans) > 20:
            print(f"  ... and {len(orphans) - 20} more")
        print("Dry run. Add --apply to delete these objects.")
        return 0

    deleted = 0
    for key in orphans:
        await storage.delete(key)
        deleted += 1
    print(f"Deleted {deleted} orphan objects.")
    return 0


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--apply", action="store_true", help="Delete found orphans")
    args = parser.parse_args()
    raise SystemExit(asyncio.run(main(args.apply)))
