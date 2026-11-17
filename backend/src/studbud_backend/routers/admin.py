import hmac
import uuid
from datetime import UTC, datetime, timedelta

from fastapi import APIRouter, Depends, Header, HTTPException, Request, status
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from ..config import get_settings
from ..db import get_db
from ..models import AccessKey, AdminAuditEvent, Session, User, UserStatus
from ..rate_limit import enforce_rate_limit
from ..schemas import (
    AdminCreateUserRequest,
    AdminUserList,
    AdminUserOut,
    AdminUserPatchRequest,
    IssuedKeyOut,
    KeyIssueRequest,
    KeyMetadata,
    UserOut,
)
from ..security import generate_access_key, hash_access_key, key_prefix, utcnow

router = APIRouter(prefix="/api/admin", tags=["admin"])


async def require_admin(
    request: Request,
    x_admin_secret: str | None = Header(default=None, alias="X-Admin-Secret"),
) -> None:
    settings = get_settings()
    if not settings.admin_api_secret:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND)
    await enforce_rate_limit(request, "admin", settings.admin_rate_limit)
    if x_admin_secret is None or not hmac.compare_digest(x_admin_secret, settings.admin_api_secret):
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid admin secret.",
        )


def _audit(
    db: AsyncSession,
    action: str,
    *,
    target_user_id: uuid.UUID | None = None,
    target_key_id: uuid.UUID | None = None,
    metadata: dict | None = None,
) -> None:
    db.add(
        AdminAuditEvent(
            action=action,
            actor_label="admin",
            target_user_id=target_user_id,
            target_key_id=target_key_id,
            metadata_json=metadata,
        )
    )


@router.post(
    "/users",
    response_model=UserOut,
    status_code=status.HTTP_201_CREATED,
    dependencies=[Depends(require_admin)],
)
async def create_user(
    payload: AdminCreateUserRequest,
    db: AsyncSession = Depends(get_db),
) -> User:
    user = User(display_name=payload.display_name.strip())
    db.add(user)
    await db.flush()
    _audit(db, "UserCreated", target_user_id=user.id)
    await db.commit()
    await db.refresh(user)
    return user


@router.get(
    "/users",
    response_model=AdminUserList,
    dependencies=[Depends(require_admin)],
)
async def list_users(db: AsyncSession = Depends(get_db)) -> AdminUserList:
    users = (await db.scalars(select(User).order_by(User.created_at.desc()))).all()
    keys = (await db.scalars(select(AccessKey).order_by(AccessKey.created_at.desc()))).all()

    keys_by_user: dict[uuid.UUID, list[KeyMetadata]] = {}
    for key in keys:
        keys_by_user.setdefault(key.user_id, []).append(KeyMetadata.model_validate(key))

    return AdminUserList(
        users=[
            AdminUserOut(
                user=UserOut.model_validate(user),
                keys=keys_by_user.get(user.id, []),
            )
            for user in users
        ]
    )


@router.patch(
    "/users/{user_id}",
    response_model=UserOut,
    dependencies=[Depends(require_admin)],
)
async def patch_user(
    user_id: uuid.UUID,
    payload: AdminUserPatchRequest,
    db: AsyncSession = Depends(get_db),
) -> User:
    user = await db.get(User, user_id)
    if user is None:
        raise HTTPException(status_code=404, detail="User not found.")

    user.status = payload.status
    if payload.status == UserStatus.disabled:
        sessions = (await db.scalars(select(Session).where(Session.user_id == user.id))).all()
        now = datetime.now(UTC)
        for session in sessions:
            if session.revoked_at is None:
                session.revoked_at = now
    _audit(
        db,
        "UserStatusChanged",
        target_user_id=user.id,
        metadata={"status": payload.status.value},
    )
    await db.commit()
    await db.refresh(user)
    return user


@router.post(
    "/users/{user_id}/keys",
    response_model=IssuedKeyOut,
    status_code=status.HTTP_201_CREATED,
    dependencies=[Depends(require_admin)],
)
async def issue_key(
    user_id: uuid.UUID,
    payload: KeyIssueRequest,
    db: AsyncSession = Depends(get_db),
) -> IssuedKeyOut:
    user = await db.get(User, user_id)
    if user is None:
        raise HTTPException(status_code=404, detail="User not found.")

    settings = get_settings()
    now = utcnow()
    expires_at = payload.expires_at or (now + timedelta(days=settings.access_key_ttl_days))
    if expires_at.tzinfo is None:
        expires_at = expires_at.replace(tzinfo=UTC)
    if expires_at <= now:
        raise HTTPException(
            status_code=422,
            detail="expiresAt must be in the future.",
        )

    plaintext = generate_access_key()
    access_key = AccessKey(
        user_id=user.id,
        key_hash=hash_access_key(plaintext),
        key_prefix=key_prefix(plaintext),
        expires_at=expires_at,
        created_by="admin",
    )
    db.add(access_key)
    await db.flush()
    _audit(
        db,
        "KeyIssued",
        target_user_id=user.id,
        target_key_id=access_key.id,
        metadata={"expires_at": expires_at.isoformat()},
    )
    await db.commit()

    return IssuedKeyOut(
        id=access_key.id,
        user_id=user.id,
        key=plaintext,
        key_prefix=access_key.key_prefix,
        expires_at=access_key.expires_at,
    )


@router.post(
    "/keys/{key_id}/revoke",
    status_code=status.HTTP_204_NO_CONTENT,
    dependencies=[Depends(require_admin)],
)
async def revoke_key(
    key_id: uuid.UUID,
    db: AsyncSession = Depends(get_db),
) -> None:
    access_key = await db.get(AccessKey, key_id)
    if access_key is None:
        raise HTTPException(status_code=404, detail="Key not found.")

    now = datetime.now(UTC)
    access_key.revoked_at = now
    sessions = (
        await db.scalars(select(Session).where(Session.access_key_id == access_key.id))
    ).all()
    for session in sessions:
        if session.revoked_at is None:
            session.revoked_at = now

    _audit(
        db,
        "KeyRevoked",
        target_user_id=access_key.user_id,
        target_key_id=access_key.id,
    )
    await db.commit()
