import asyncio
import os
import subprocess
import sys
from pathlib import Path

import pytest
from sqlalchemy import text

os.environ["DATABASE_URL"] = "postgresql+asyncpg://studbud:studbud@127.0.0.1:5432/studbud_test"
os.environ["KEY_PEPPER"] = "test-only-pepper"
os.environ["ADMIN_API_SECRET"] = "test-admin-secret"
os.environ["WORKER_ENABLED"] = "false"
os.environ["AUTO_CREATE_TABLES"] = "true"
os.environ["STORAGE_DIR"] = "storage-test"
# Tests must be deterministic and offline: do not pick up developer provider keys
# from backend/.env.
os.environ["GROQ_API_KEY"] = ""
os.environ["GEMINI_API_KEY"] = ""
os.environ["VISION_PROVIDER"] = "none"
os.environ["EMBEDDING_PROVIDER"] = "hash"

SAMPLE_PDF = Path(__file__).parent / "sample_networks.pdf"


async def _prepare_database() -> None:
    import asyncpg

    connection = await asyncpg.connect(
        host="127.0.0.1",
        port=5432,
        user="studbud",
        password="studbud",
        database="postgres",
    )
    try:
        exists = await connection.fetchval(
            "SELECT 1 FROM pg_database WHERE datname = 'studbud_test'"
        )
        if not exists:
            await connection.execute("CREATE DATABASE studbud_test")
    finally:
        await connection.close()

    test_connection = await asyncpg.connect(
        host="127.0.0.1",
        port=5432,
        user="studbud",
        password="studbud",
        database="studbud_test",
    )
    try:
        await test_connection.execute("DROP SCHEMA public CASCADE")
        await test_connection.execute("CREATE SCHEMA public")
    finally:
        await test_connection.close()

    from studbud_backend.db import engine, init_db

    await init_db()
    await engine.dispose()


@pytest.fixture(scope="session", autouse=True)
def database() -> None:
    try:
        asyncio.run(_prepare_database())
    except (OSError, ConnectionError) as exc:  # pragma: no cover - environment guard
        pytest.skip(f"PostgreSQL is not available for tests: {exc}")

    if not SAMPLE_PDF.exists():
        subprocess.run(
            [sys.executable, str(SAMPLE_PDF.parent / "make_sample_pdf.py")],
            check=True,
            cwd=SAMPLE_PDF.parent.parent,
        )


@pytest.fixture(autouse=True)
async def clean_tables(database: None) -> None:
    from studbud_backend.db import engine

    async with engine.begin() as connection:
        await connection.execute(
            text(
                "TRUNCATE admin_audit_events, explanation_citations, explanations, "
                "ingestion_jobs, document_chunks, documents, sessions, access_keys, users "
                "RESTART IDENTITY CASCADE"
            )
        )
