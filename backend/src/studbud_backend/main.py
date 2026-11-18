import asyncio
import hmac
import logging
import time
import uuid
from contextlib import asynccontextmanager
from urllib.parse import urlsplit

from fastapi import FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
from sqlalchemy import text

from .config import get_settings
from .db import SessionLocal, engine, init_db
from .routers import admin, auth, documents, explanations, search
from .worker import run_worker

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s %(levelname)s %(name)s %(message)s",
)
logger = logging.getLogger(__name__)

SAFE_METHODS = {"GET", "HEAD", "OPTIONS", "TRACE"}


@asynccontextmanager
async def lifespan(app: FastAPI):
    settings = get_settings()
    if settings.key_pepper == "dev-only-pepper-change-me":
        logger.warning("KEY_PEPPER is using the development default; set it in production.")

    if settings.environment.lower() == "production":
        if settings.storage_backend.lower() == "local" or (
            settings.storage_backend.lower() == "auto"
            and not (settings.r2_endpoint and settings.r2_bucket)
        ):
            raise RuntimeError(
                "Production storage must use R2. Set STORAGE_BACKEND=r2 and the R2 "
                "credentials; HF Spaces and Render filesystems are ephemeral."
            )
        if not settings.admin_api_secret:
            raise RuntimeError("ADMIN_API_SECRET is required in production.")
        if settings.cookie_samesite.lower() == "none" and not settings.cookie_secure:
            raise RuntimeError("SameSite=None requires COOKIE_SECURE=true.")

    if settings.auto_create_tables:
        await init_db()

    stop_event = asyncio.Event()
    worker_task: asyncio.Task | None = None
    if settings.worker_enabled:
        worker_task = asyncio.create_task(run_worker(stop_event))

    yield

    stop_event.set()
    if worker_task is not None:
        await worker_task
    await engine.dispose()


settings = get_settings()

if settings.sentry_dsn:
    import sentry_sdk

    sentry_sdk.init(
        dsn=settings.sentry_dsn,
        environment=settings.environment,
        traces_sample_rate=settings.sentry_traces_sample_rate,
        send_default_pii=False,
        max_request_body_size="never",
    )
    logger.info("Sentry error reporting enabled")

app = FastAPI(title=settings.app_name, version="0.1.0", lifespan=lifespan)


@app.middleware("http")
async def request_observability(request: Request, call_next):
    request_id = request.headers.get("x-request-id") or uuid.uuid4().hex[:12]
    request.state.request_id = request_id
    started = time.perf_counter()

    if settings.sentry_dsn:
        import sentry_sdk

        sentry_sdk.set_tag("request_id", request_id)

    try:
        response = await call_next(request)
    except Exception:
        logger.exception(
            "request_id=%s method=%s path=%s unhandled",
            request_id,
            request.method,
            request.url.path,
        )
        raise

    duration_ms = (time.perf_counter() - started) * 1000
    response.headers["X-Request-ID"] = request_id
    logger.info(
        "request_id=%s method=%s path=%s status=%s duration_ms=%.1f",
        request_id,
        request.method,
        request.url.path,
        response.status_code,
        duration_ms,
    )
    return response


@app.middleware("http")
async def browser_request_guards(request: Request, call_next):
    """Reject unknown browser origins and enforce CSRF double-submit tokens."""
    settings = get_settings()
    origin = request.headers.get("origin")
    if origin:
        parsed_origin = urlsplit(origin)
        same_origin = (
            parsed_origin.scheme in {"http", "https"} and parsed_origin.netloc == request.url.netloc
        )
        if not same_origin and origin not in settings.frontend_origin_list:
            return JSONResponse(status_code=403, content={"detail": "Origin not allowed."})

    # Admin endpoints authenticate with a custom header, not a cookie session.
    # CSRF does not apply; the secret cannot be set by a cross-site form.
    is_admin_request = request.url.path.startswith("/api/admin/")
    # Sign-in authenticates with the key in the request body. A stale session
    # cookie must not block re-authentication, so CSRF does not apply here either.
    is_sign_in = request.url.path.rstrip("/") == "/api/auth/sign-in"
    if (
        request.method not in SAFE_METHODS
        and not is_admin_request
        and not is_sign_in
        and settings.session_cookie_name in request.cookies
    ):
        cookie_token = request.cookies.get(settings.csrf_cookie_name, "")
        header_token = request.headers.get("x-csrf-token", "")
        if (
            not cookie_token
            or not header_token
            or not hmac.compare_digest(cookie_token, header_token)
        ):
            return JSONResponse(
                status_code=403,
                content={"detail": "Missing or invalid CSRF token."},
            )

    return await call_next(request)


app.add_middleware(
    CORSMiddleware,
    allow_origins=settings.frontend_origin_list,
    allow_credentials=True,
    allow_methods=["GET", "POST", "PATCH", "PUT", "DELETE", "OPTIONS"],
    allow_headers=["Content-Type", "X-CSRF-Token", "X-Admin-Secret", "X-Request-ID"],
    expose_headers=["X-Request-ID", "X-CSRF-Token"],
)

app.include_router(auth.router)
app.include_router(admin.router)
app.include_router(documents.router)
app.include_router(search.router)
app.include_router(explanations.router)


@app.get("/healthz", tags=["ops"])
async def healthz():
    try:
        async with SessionLocal() as db:
            await db.execute(text("SELECT 1"))
        return {"status": "ok"}
    except Exception:
        logger.exception("Health check failed")
        return JSONResponse(status_code=503, content={"status": "unavailable"})
