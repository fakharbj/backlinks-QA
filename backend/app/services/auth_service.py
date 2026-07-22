"""Authentication & token lifecycle.

Handles registration (user + workspace + admin membership), credential
verification with lockout, JWT issuance, refresh rotation with reuse-detection,
and logout (Redis denylist + DB revocation).
"""

from __future__ import annotations

import asyncio
import uuid
from datetime import datetime, timedelta, timezone

import jwt
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import settings
from app.core.errors import AuthenticationError, ConflictError
from app.core.logging import get_logger
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

log = get_logger("services.auth")

_DUMMY_HASH = hash_password("dummy-password-placeholder")  # constant-time login for unknown emails


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

    # Argon2 is CPU-heavy (~100ms+) — run it off the event loop.
    password_hash = await asyncio.to_thread(hash_password, password)
    user = User(email=email.lower(), full_name=full_name, password_hash=password_hash)
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


async def authenticate(
    db: AsyncSession, *, email: str, password: str,
    ip_address: str | None = None, user_agent: str | None = None,
) -> User:
    user = (
        await db.execute(select(User).where(User.email == email.lower()))
    ).scalar_one_or_none()

    if user is None:
        # Constant-ish work to reduce user-enumeration timing signal.
        await asyncio.to_thread(verify_password, password, _DUMMY_HASH)
        raise AuthenticationError("Invalid email or password")

    if user.locked_until and user.locked_until > _now():
        raise AuthenticationError("Account temporarily locked due to failed logins")

    if not await asyncio.to_thread(verify_password, password, user.password_hash):
        user.failed_login_attempts += 1
        if user.failed_login_attempts >= settings.LOGIN_MAX_FAILED_ATTEMPTS:
            user.locked_until = _now() + timedelta(minutes=settings.LOGIN_LOCKOUT_MINUTES)
        await audit_service.record(
            db, action=AuditAction.LOGIN_FAILED, actor_user_id=user.id,
            summary=f"Failed login ({user.failed_login_attempts})",
            ip_address=ip_address, user_agent=user_agent,
        )
        raise AuthenticationError("Invalid email or password")

    if not user.is_active:
        # Deactivation is a login block ONLY — the person's links, tasks and
        # reports stay untouched in every historical view.
        raise AuthenticationError("This account is inactive. Please contact your admin.")

    # Success: reset counters, opportunistically rehash if params changed.
    user.failed_login_attempts = 0
    user.locked_until = None
    user.last_login_at = _now()
    if password_needs_rehash(user.password_hash):
        user.password_hash = await asyncio.to_thread(hash_password, password)
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
    db: AsyncSession, *, refresh_token: str, workspace_id: uuid.UUID | None = None,
    ip_address: str | None = None, user_agent: str | None = None,
    enforce_ip_bind: bool = False,
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

    if stored is None or stored.expires_at < _now():
        raise AuthenticationError("Refresh token expired or revoked")
    if stored.revoked:
        # Rotation grace for HONEST clients: two tabs (or a request racing the
        # 10-min proactive refresh) can present the just-rotated token. If this
        # token was rotated moments ago and its replacement chain is still
        # alive, follow the chain to the live head and rotate THAT — both tabs
        # end up with valid sessions. Without this, any stale reuse revoked the
        # user's ENTIRE token lineage, logging every session out ("random
        # logout" reports). Beyond the grace window we reject just this call —
        # never the whole lineage (an old tab waking from sleep is not theft).
        grace = timedelta(seconds=max(0, settings.REFRESH_REUSE_GRACE_SECONDS))
        rotated_recently = stored.updated_at is not None and (_now() - stored.updated_at) <= grace
        head = stored
        hops = 0
        while rotated_recently and head.replaced_by_jti and hops < 5:
            nxt = (
                await db.execute(
                    select(RefreshToken).where(RefreshToken.jti == head.replaced_by_jti)
                )
            ).scalar_one_or_none()
            if nxt is None:
                break
            head = nxt
            hops += 1
        if rotated_recently and not head.revoked and head.expires_at >= _now():
            log.info("refresh_reuse_grace", user_id=str(user_id), hops=hops)
            stored = head  # rotate the live head below — honest race resolved
        else:
            log.warning(
                "refresh_reuse_rejected", user_id=str(user_id),
                rotated_recently=rotated_recently,
            )
            raise AuthenticationError("Refresh token expired or revoked")
    jti = stored.jti

    # IP-bound sessions (Settings → Security): if the network address changed
    # since this session was issued, revoke it — the user signs in again.
    # Runs AFTER the reuse-grace resolution so honest multi-tab races on one
    # IP never trip it; only compares when BOTH sides are known (fail-open).
    if (
        enforce_ip_bind
        and ip_address
        and stored.ip_address
        and stored.ip_address != ip_address
    ):
        stored.revoked = True
        await revoke_jti(jti, _ttl(stored.expires_at))
        await audit_service.record(
            db, action=AuditAction.LOGOUT, actor_user_id=user_id,
            summary=f"Session revoked — network address changed ({stored.ip_address} → {ip_address})",
            ip_address=ip_address, user_agent=user_agent,
        )
        await db.commit()
        raise AuthenticationError(
            "Your session ended because your network address changed. Please sign in again."
        )

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

    # Full IP-allowed check at refresh (owner rule): an enforced user whose
    # CURRENT network is not allowed cannot renew — the lineage is revoked and
    # the event audited. Complements the per-request check in deps and the
    # optional bind_sessions equality check below. Fail-open on internal error.
    if ip_address:
        try:
            from app.services import login_ip_service

            _rules = await login_ip_service.get_rules_cached(db)
            if login_ip_service.rules_can_enforce(_rules):
                _tm = await login_ip_service.team_mode_cached(db, _rules, user_id)
                _ok, _why = login_ip_service.is_allowed(
                    _rules, ip_address, user_id, membership.role.value, team_mode=_tm
                )
                if not _ok:
                    stored.revoked = True
                    await revoke_jti(jti, _ttl(stored.expires_at))
                    await audit_service.record(
                        db, action=AuditAction.LOGOUT, actor_user_id=user_id,
                        summary=f"Refresh denied — IP not allowed ({ip_address}: {_why})",
                        ip_address=ip_address, user_agent=user_agent,
                    )
                    await db.commit()
                    raise AuthenticationError(
                        "Your session ended because this network isn't allowed. "
                        "Sign in again from an approved IP."
                    )
        except AuthenticationError:
            raise
        except Exception:  # noqa: BLE001
            pass

    # Rotate: mark old revoked, mint new, link lineage.
    new_access, _, _ = create_token(
        subject=user.id, token_type="access",
        workspace_id=membership.workspace_id, role=membership.role.value,
    )
    new_refresh, new_jti, expires = create_token(subject=user.id, token_type="refresh")
    stored.revoked = True
    stored.replaced_by_jti = new_jti
    await revoke_jti(jti, _ttl(stored.expires_at))
    db.add(RefreshToken(
        user_id=user.id, jti=new_jti, expires_at=expires,
        # Carry the session metadata: current values when the proxy supplied
        # them, else whatever the lineage already knew.
        ip_address=ip_address or stored.ip_address,
        user_agent=user_agent or stored.user_agent,
    ))

    return TokenPair(
        access_token=new_access,
        refresh_token=new_refresh,
        expires_in=settings.ACCESS_TOKEN_TTL_MINUTES * 60,
    )


async def logout(
    db: AsyncSession, *, refresh_token: str,
    ip_address: str | None = None, user_agent: str | None = None,
) -> None:
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
        await audit_service.record(
            db, action=AuditAction.LOGOUT, actor_user_id=stored.user_id,
            summary="Signed out", ip_address=ip_address, user_agent=user_agent,
        )


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
