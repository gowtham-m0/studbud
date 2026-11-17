from dataclasses import dataclass
from datetime import UTC, datetime, timedelta

from fastapi import Depends, HTTPException, Request, status
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from .config import get_settings
from .db import get_db
from .models import AccessKey, Session, User, UserStatus
from .security import hash_session_token


@dataclass
class SessionContext:
    user: User
    session: Session
    access_key: AccessKey


def _unauthorized() -> HTTPException:
    return HTTPException(
        status_code=status.HTTP_401_UNAUTHORIZED,
        detail="Authentication required.",
    )


async def get_session_context(
    request: Request,
    db: AsyncSession = Depends(get_db),
) -> SessionContext:
    settings = get_settings()
    raw_token = request.cookies.get(settings.session_cookie_name)
    if not raw_token:
        raise _unauthorized()

    session = await db.scalar(
        select(Session).where(Session.token_hash == hash_session_token(raw_token))
    )
    if session is None or session.revoked_at is not None:
        raise _unauthorized()

    now = datetime.now(UTC)
    if session.expires_at <= now:
        raise _unauthorized()

    access_key = await db.get(AccessKey, session.access_key_id)
    if access_key is None or access_key.revoked_at is not None or access_key.expires_at <= now:
        raise _unauthorized()

    user = await db.get(User, session.user_id)
    if user is None or user.status != UserStatus.active:
        raise _unauthorized()

    if session.last_seen_at is None or now - session.last_seen_at > timedelta(minutes=5):
        session.last_seen_at = now
        await db.commit()

    return SessionContext(user=user, session=session, access_key=access_key)


async def get_current_user(
    context: SessionContext = Depends(get_session_context),
) -> User:
    return context.user
