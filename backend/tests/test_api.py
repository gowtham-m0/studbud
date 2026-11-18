import uuid
from datetime import UTC, datetime, timedelta
from pathlib import Path

import httpx
import pytest
from sqlalchemy import select

from studbud_backend.config import get_settings
from studbud_backend.db import SessionLocal
from studbud_backend.ingestion.pipeline import process_document
from studbud_backend.models import AccessKey, IngestionJob

ADMIN_HEADERS = {"X-Admin-Secret": "test-admin-secret"}
SAMPLE_PDF = Path(__file__).parent / "sample_networks.pdf"


@pytest.fixture
async def client():
    from studbud_backend.main import app

    transport = httpx.ASGITransport(app=app)
    async with httpx.AsyncClient(transport=transport, base_url="http://testserver") as test_client:
        yield test_client


def csrf_headers(client: httpx.AsyncClient) -> dict[str, str]:
    token = client.cookies.get("sb_csrf")
    return {"X-CSRF-Token": token} if token else {}


async def create_user_with_key(client: httpx.AsyncClient, name: str = "Test Learner") -> dict:
    headers = {**ADMIN_HEADERS, **csrf_headers(client)}
    user_response = await client.post(
        "/api/admin/users", headers=headers, json={"display_name": name}
    )
    assert user_response.status_code == 201, user_response.text
    user = user_response.json()

    key_response = await client.post(
        f"/api/admin/users/{user['id']}/keys", headers=headers, json={}
    )
    assert key_response.status_code == 201, key_response.text
    issued = key_response.json()
    return {"user": user, **issued}


async def sign_in(client: httpx.AsyncClient, key: str) -> httpx.Response:
    response = await client.post("/api/auth/sign-in", json={"key": key})
    assert response.status_code == 204, response.text
    return response


async def test_admin_list_user_keys(client: httpx.AsyncClient) -> None:
    issued = await create_user_with_key(client, "Key List")

    response = await client.get(
        f"/api/admin/users/{issued['user']['id']}/keys", headers=ADMIN_HEADERS
    )
    assert response.status_code == 200, response.text

    keys = response.json()
    assert len(keys) == 1
    assert keys[0]["id"] == issued["id"]
    assert keys[0]["key_prefix"].startswith("SB_")
    assert "key" not in keys[0]
    assert "key_hash" not in keys[0]


async def test_admin_list_users_returns_top_level_id(
    client: httpx.AsyncClient,
) -> None:
    issued = await create_user_with_key(client, "List Shape")
    response = await client.get("/api/admin/users", headers=ADMIN_HEADERS)
    assert response.status_code == 200, response.text

    users = response.json()["users"]
    match = next(user for user in users if user["id"] == issued["user"]["id"])
    assert "user" not in match
    assert match["display_name"] == "List Shape"
    assert match["keys"][0]["id"] == issued["id"]


async def test_same_origin_admin_post(client: httpx.AsyncClient) -> None:
    response = await client.post(
        "/api/admin/users",
        headers={**ADMIN_HEADERS, "Origin": "http://testserver"},
        json={"display_name": "Swagger User"},
    )
    assert response.status_code == 201, response.text


async def test_admin_post_with_session_skips_csrf(client: httpx.AsyncClient) -> None:
    issued = await create_user_with_key(client)
    await sign_in(client, issued["key"])

    response = await client.post(
        "/api/admin/users",
        headers={**ADMIN_HEADERS, "Origin": "http://testserver"},
        json={"display_name": "Admin While Signed In"},
    )
    assert response.status_code == 201, response.text


async def test_sign_in_returns_csrf_token_header(client: httpx.AsyncClient) -> None:
    issued = await create_user_with_key(client)
    response = await sign_in(client, issued["key"])

    token = response.headers.get("X-CSRF-Token")
    assert token
    assert token == client.cookies.get("sb_csrf")


async def test_sign_in_with_stale_session_skips_csrf(client: httpx.AsyncClient) -> None:
    issued = await create_user_with_key(client)

    await sign_in(client, issued["key"])
    assert client.cookies.get("sb_session")

    # Re-authenticating while a session cookie is present must not be blocked by
    # the CSRF guard; sign-in does not rely on the cookie for authentication.
    again = await client.post("/api/auth/sign-in", json={"key": issued["key"]})
    assert again.status_code == 204, again.text


async def test_admin_requires_secret(client: httpx.AsyncClient) -> None:
    response = await client.post("/api/admin/users", json={"display_name": "Nope"})
    assert response.status_code == 401

    response = await client.post(
        "/api/admin/users",
        headers={"X-Admin-Secret": "wrong"},
        json={"display_name": "Nope"},
    )
    assert response.status_code == 401


async def test_key_sign_in_lifecycle(client: httpx.AsyncClient) -> None:
    issued = await create_user_with_key(client)
    assert issued["key"].startswith("sb_")
    assert "key_hash" not in issued

    invalid = await client.post("/api/auth/sign-in", json={"key": "sb_NOT-A-REAL-KEY"})
    assert invalid.status_code == 401
    assert "invalid" in invalid.json()["detail"].lower()

    await sign_in(client, issued["key"])
    assert client.cookies.get("sb_session")
    assert client.cookies.get("sb_csrf")

    me = await client.get("/api/auth/me")
    assert me.status_code == 200
    assert me.json()["user"]["display_name"] == "Test Learner"

    blocked_sign_out = await client.post("/api/auth/sign-out")
    assert blocked_sign_out.status_code == 403

    sign_out = await client.post("/api/auth/sign-out", headers=csrf_headers(client))
    assert sign_out.status_code == 204
    assert (await client.get("/api/auth/me")).status_code == 401


async def test_expired_and_revoked_keys(client: httpx.AsyncClient) -> None:
    issued = await create_user_with_key(client)

    past = (datetime.now(UTC) - timedelta(days=1)).isoformat()
    rejected = await client.post(
        f"/api/admin/users/{issued['user']['id']}/keys",
        headers=ADMIN_HEADERS,
        json={"expires_at": past},
    )
    assert rejected.status_code == 422

    async with SessionLocal() as db:
        access_key = await db.get(AccessKey, uuid.UUID(issued["id"]))
        assert access_key is not None
        access_key.expires_at = datetime.now(UTC) - timedelta(minutes=1)
        await db.commit()

    expired = await client.post("/api/auth/sign-in", json={"key": issued["key"]})
    assert expired.status_code == 401

    fresh = await create_user_with_key(client, "Revoked Learner")
    await sign_in(client, fresh["key"])
    assert (await client.get("/api/auth/me")).status_code == 200

    revoke = await client.post(
        f"/api/admin/keys/{fresh['id']}/revoke",
        headers={**ADMIN_HEADERS, **csrf_headers(client)},
    )
    assert revoke.status_code == 204
    assert (await client.get("/api/auth/me")).status_code == 401


async def test_upload_quotas(client: httpx.AsyncClient, monkeypatch: pytest.MonkeyPatch) -> None:
    issued = await create_user_with_key(client)
    await sign_in(client, issued["key"])
    settings = get_settings()

    monkeypatch.setattr(settings, "user_max_documents", 0)
    blocked = await client.post(
        "/api/documents",
        files={"file": ("networks.pdf", SAMPLE_PDF.read_bytes(), "application/pdf")},
        headers=csrf_headers(client),
    )
    assert blocked.status_code == 403
    assert "Library limit" in blocked.json()["detail"]

    monkeypatch.setattr(settings, "user_max_documents", 50)
    monkeypatch.setattr(settings, "user_max_storage_mb", 0)
    too_large = await client.post(
        "/api/documents",
        files={"file": ("networks.pdf", SAMPLE_PDF.read_bytes(), "application/pdf")},
        headers=csrf_headers(client),
    )
    assert too_large.status_code == 413
    assert "Storage quota" in too_large.json()["detail"]


async def test_upload_search_explanation_boundaries(
    client: httpx.AsyncClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    issued = await create_user_with_key(client)
    await sign_in(client, issued["key"])

    upload = await client.post(
        "/api/documents",
        files={"file": ("networks.pdf", SAMPLE_PDF.read_bytes(), "application/pdf")},
        headers=csrf_headers(client),
    )
    assert upload.status_code == 202, upload.text
    document_id = upload.json()["document_id"]

    async with SessionLocal() as db:
        job = await db.scalar(
            select(IngestionJob).where(IngestionJob.document_id == uuid.UUID(document_id))
        )
        assert job is not None
        job_id = job.id

    await process_document(uuid.UUID(document_id), job_id)

    document = await client.get(f"/api/documents/{document_id}")
    assert document.status_code == 200
    assert document.json()["status"] == "ready"
    assert document.json()["page_count"] == 3

    assets = await client.get(f"/api/documents/{document_id}/assets", params={"page": 2})
    assert assets.status_code == 200
    page_assets = assets.json()
    assert page_assets
    assert page_assets[0]["kind"] == "page"
    image = await client.get(page_assets[0]["content_path"])
    assert image.status_code == 200
    assert image.headers["content-type"].startswith("image/")

    figure_assets = [asset for asset in page_assets if asset["kind"] == "figure"]
    assert figure_assets, "the sample diagram should be extracted as a figure"
    figure_image = await client.get(figure_assets[0]["content_path"])
    assert figure_image.status_code == 200
    assert figure_image.headers["content-type"].startswith("image/")

    search = await client.get("/api/search", params={"q": "tcp handshake"})
    assert search.status_code == 200
    results = search.json()["results"]
    assert results
    top = results[0]
    assert top["section_title"] == "TCP Three-Way Handshake"
    assert top["page_start"] == 2
    assert "##" not in top["snippet"]

    settings = get_settings()
    monkeypatch.setattr(settings, "user_daily_explanations", 0)
    quota_blocked = await client.post(
        "/api/explanations",
        json={"chunk_id": top["chunk_id"], "question": "Explain the handshake"},
        headers=csrf_headers(client),
    )
    assert quota_blocked.status_code == 429
    assert "Daily explanation limit" in quota_blocked.json()["detail"]

    monkeypatch.setattr(settings, "user_daily_explanations", 100)
    explanation = await client.post(
        "/api/explanations",
        json={"chunk_id": top["chunk_id"], "question": "Explain the handshake"},
        headers=csrf_headers(client),
    )
    assert explanation.status_code == 503

    second = await create_user_with_key(client, "Other Learner")
    from studbud_backend.main import app as application

    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app=application),
        base_url="http://testserver",
    ) as other_client:
        await sign_in(other_client, second["key"])

        other_search = await other_client.get("/api/search", params={"q": "tcp handshake"})
        assert other_search.status_code == 200
        assert other_search.json()["results"] == []

        assert (await other_client.get(f"/api/documents/{document_id}")).status_code == 404
        denied_assets = await other_client.get(f"/api/documents/{document_id}/assets")
        assert denied_assets.status_code == 404
        denied = await other_client.post(
            "/api/explanations",
            json={"chunk_id": top["chunk_id"]},
            headers=csrf_headers(other_client),
        )
        assert denied.status_code == 404

    delete = await client.delete(f"/api/documents/{document_id}", headers=csrf_headers(client))
    assert delete.status_code == 204

    after_delete = await client.get("/api/search", params={"q": "tcp handshake"})
    assert after_delete.json()["results"] == []
