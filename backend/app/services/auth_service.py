"""Authentication & token lifecycle.

Handles registration (user + workspace + admin membership), credential
verification with lockout, JWT issuance, refresh rotation with reuse-detection,
and logout (Redis denylist + DB revocation).
"""

from __future__ import annotations

import uuid
from datetime import datetime, timedelta, timezone

import jwt
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import settings
from app.core.errors import AuthenticationError, ConflictError
from app.core.rbac import Role
from app.core.redis import revoke_jti
from app.core.security import (
    create_token,
    decode_token,
    hash_password,
    password_needs_rehash,
    verify_password,
)
from app.core.utils import unique_slug
from app.models.enums import AuditAction
from app.models.user import RefreshToken, User, Workspace, WorkspaceMember
from app.schemas.auth import TokenPair
from app.services import audit_service


def _now() -> datetime:
    return datetime.now(timezone.utc)


async def register(
    db: AsyncSession, *, email: str, password: str, full_name: str, workspace_name: str
) -> tuple[User, Workspace]:
    existing = (
        await db.execute(select(User).where(User.email == email.lower()))
    ).scalar_one_or_none()
    if existing is not None:
        raise ConflictError("An account with this email already exists")

    user = User(email=email.lower(), full_name=full_name, password_hash=hash_password(password))
    workspace = Workspace(name=workspace_name, slug=unique_slug(workspace_name))
    db.add_all([user, workspace])
    await db.flush()

    db.add(WorkspaceMember(workspace_id=workspace.id, user_id=user.id, role=Role.ADMIN))
    await audit_service.record(
        db, action=AuditAction.CREATE, actor_user_id=user.id, workspace_id=workspace.id,
        entity_type="workspace", entity_id=workspace.id, summary="Workspace created on signup",
    )
    await db.flush()
    return user, workspace


async def authenticate(db: AsyncSession, *, email: str, password: str) -> User:
    user = (
        await db.execute(select(User).where(User.email == email.lower()))
    ).scalar_one_or_none()

    if user is None:
        # Constant-ish work to reduce user-enumeration timing signal.
        verify_password(password, hash_password("dummy-password-placeholder"))
        raise AuthenticationError("Invalid email or password")

    if user.locked_until and user.locked_until > _now():
        raise AuthenticationError("Account temporarily locked due to failed logins")

    if not verify_password(password, user.password_hash):
        user.failed_login_attempts += 1
        if user.failed_login_attempts >= settings.LOGIN_MAX_FAILED_ATTEMPTS:
            user.locked_until = _now() + timedelta(minutes=settings.LOGIN_LOCKOUT_MINUTES)
        await audit_service.record(
            db, action=AuditAction.LOGIN_FAILED, actor_user_id=user.id,
            summary=f"Failed login ({user.failed_login_attempts})",
        )
        raise AuthenticationError("Invalid email or password")

    if not user.is_active:
        raise AuthenticationError("Account is disabled")

    # Success: reset counters, opportunistically rehash if params changed.
    user.failed_login_attempts = 0
    user.locked_until = None
    user.last_login_at = _now()
    if password_needs_rehash(user.password_hash):
        user.password_hash = hash_password(password)
    return user


async def default_workspace(db: AsyncSession, user_id: uuid.UUID) -> WorkspaceMember | None:
    return (
        await db.execute(
            select(WorkspaceMember)
            .where(WorkspaceMember.user_id == user_id)
            .order_by(WorkspaceMember.created_at.asc())
        )
    ).scalars().first()


async def issue_tokens(
    db: AsyncSession,
    *,
    user: User,
    workspace_id: uuid.UUID,
    role: Role,
    user_agent: str | None = None,
    ip_address: str | None = None,
) -> TokenPair:
    access, _, _ = create_token(
        subject=user.id, token_type="access", workspace_id=workspace_id, role=role.value
    )
    refresh, jti, expires = create_token(subject=user.id, token_type="refresh")
    db.add(
        RefreshToken(
            user_id=user.id, jti=jti, expires_at=expires,
            user_agent=user_agent, ip_address=ip_address,
        )
    )
    return TokenPair(
        access_token=access,
        refresh_token=refresh,
        expires_in=settings.ACCESS_TOKEN_TTL_MINUTES * 60,
    )


async def rotate_refresh(
    db: AsyncSession, *, refresh_token: str, workspace_id: uuid.UUID | None = None
) -> TokenPair:
    try:
        payload = decode_token(refresh_token, expected_type="refresh")
    except jwt.PyJWTError as exc:
        raise AuthenticationError("Invalid refresh token") from exc

    jti = payload["jti"]
    user_id = uuid.UUID(payload["sub"])
    stored = (
        await db.execute(select(RefreshToken).where(RefreshToken.jti == jti))
    ).scalar_one_or_none()

    if stored is None or stored.revoked or stored.expires_at < _now():
        # Reuse of a revoked token → revoke the whole lineage (token theft defence).
        if stored is not None and stored.revoked:
            await _revoke_user_tokens(db, user_id)
        raise AuthenticationError("Refresh token expired or revoked")

    user = await db.get(User, user_id)
    if user is None or not user.is_active:
        raise AuthenticationError("User not found or inactive")

    membership = await default_workspace(db, user_id) if workspace_id is None else (
        await db.execute(
            select(WorkspaceMember).where(
                WorkspaceMember.user_id == user_id,
                WorkspaceMember.workspace_id == workspace_id,
            )
        )
    ).scalar_one_or_none()
    if membership is None:
        raise AuthenticationError("No workspace membership for refresh")

    # Rotate: mark old revoked, mint new, link lineage.
    new_access, _, _ = create_token(
        subject=user.id, token_type="access",
        workspace_id=membership.workspace_id, role=membership.role.value,
    )
    new_refresh, new_jti, expires = create_token(subject=user.id, token_type="refresh")
    stored.revoked = True
    stored.replaced_by_jti = new_jti
    await revoke_jti(jti, _ttl(stored.expires_at))
    db.add(RefreshToken(user_id=user.id, jti=new_jti, expires_at=expires))

    return TokenPair(
        access_token=new_access,
        refresh_token=new_refresh,
        expires_in=settings.ACCESS_TOKEN_TTL_MINUTES * 60,
    )


async def logout(db: AsyncSession, *, refresh_token: str) -> None:
    try:
        payload = decode_token(refresh_token, expected_type="refresh")
    except jwt.PyJWTError:
        return  # already invalid → nothing to do
    jti = payload["jti"]
    stored = (
        await db.execute(select(RefreshToken).where(RefreshToken.jti == jti))
    ).scalar_one_or_none()
    if stored is not None and not stored.revoked:
        stored.revoked = True
        await revoke_jti(jti, _ttl(stored.expires_at))


async def _revoke_user_tokens(db: AsyncSession, user_id: uuid.UUID) -> None:
    rows = (
        await db.execute(
            select(RefreshToken).where(
                RefreshToken.user_id == user_id, RefreshToken.revoked.is_(False)
            )
        )
    ).scalars().all()
    for token in rows:
        token.revoked = True
        await revoke_jti(token.jti, _ttl(token.expires_at))


def _ttl(expires_at: datetime) -> int:
    return max(1, int((expires_at - _now()).total_seconds()))
