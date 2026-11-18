import secrets
from datetime import UTC, datetime

from fastapi import APIRouter, Depends, HTTPException, Request, Response, status
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from ..config import get_settings
from ..db import get_db
from ..deps import SessionContext, get_session_context
from ..models import AccessKey, Session, User, UserStatus
from ..rate_limit import enforce_rate_limit
from ..schemas import SessionInfo, SignInRequest, UserOut
from ..security import (
    generate_session_token,
    hash_access_key,
    hash_session_token,
    session_expiry,
)

router = APIRouter(prefix="/api/auth", tags=["auth"])


@router.post("/sign-in", status_code=status.HTTP_204_NO_CONTENT)
async def sign_in(
    payload: SignInRequest,
    request: Request,
    response: Response,
    db: AsyncSession = Depends(get_db),
) -> None:
    settings = get_settings()
    await enforce_rate_limit(request, "sign-in", settings.sign_in_rate_limit)

    key_hash = hash_access_key(payload.key)
    row = (
        await db.execute(
            select(AccessKey, User)
            .join(User, User.id == AccessKey.user_id)
            .where(AccessKey.key_hash == key_hash)
        )
    ).one_or_none()

    now = datetime.now(UTC)
    if row is None:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid or expired access key.",
        )

    access_key, user = row
    if (
        access_key.revoked_at is not None
        or access_key.expires_at <= now
        or user.status != UserStatus.active
    ):
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid or expired access key.",
        )

    token = generate_session_token()
    csrf_token = secrets.token_urlsafe(24)
    expires_at = session_expiry(access_key.expires_at, now)
    session = Session(
        user_id=user.id,
        access_key_id=access_key.id,
        token_hash=hash_session_token(token),
        expires_at=expires_at,
    )
    db.add(session)
    access_key.last_used_at = now
    await db.commit()

    max_age = max(1, int((expires_at - now).total_seconds()))
    cookie_kwargs = {
        "max_age": max_age,
        "expires": expires_at,
        "path": "/",
        "secure": settings.cookie_secure,
        "samesite": settings.cookie_samesite,
        "domain": settings.cookie_domain,
    }
    response.set_cookie(
        key=settings.session_cookie_name,
        value=token,
        httponly=True,
        **cookie_kwargs,
    )
    response.set_cookie(
        key=settings.csrf_cookie_name,
        value=csrf_token,
        httponly=False,
        **cookie_kwargs,
    )
    # Cross-origin frontends cannot read the API host's cookie jar. Expose the
    # token in a response header so the client can replay it as a request header.
    response.headers["X-CSRF-Token"] = csrf_token


@router.post("/sign-out", status_code=status.HTTP_204_NO_CONTENT)
async def sign_out(
    response: Response,
    context: SessionContext = Depends(get_session_context),
    db: AsyncSession = Depends(get_db),
) -> None:
    settings = get_settings()
    context.session.revoked_at = datetime.now(UTC)
    await db.commit()
    response.delete_cookie(
        settings.session_cookie_name,
        path="/",
        domain=settings.cookie_domain,
    )
    response.delete_cookie(
        settings.csrf_cookie_name,
        path="/",
        domain=settings.cookie_domain,
    )


@router.get("/me", response_model=SessionInfo)
async def me(context: SessionContext = Depends(get_session_context)) -> SessionInfo:
    return SessionInfo(
        user=UserOut.model_validate(context.user),
        session_expires_at=context.session.expires_at,
        key_expires_at=context.access_key.expires_at,
    )
