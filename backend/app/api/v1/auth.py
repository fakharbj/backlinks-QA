"""Auth endpoints: register, login, refresh, logout, me."""

from __future__ import annotations

from fastapi import APIRouter, Request, status
from pydantic import BaseModel
from sqlalchemy import select

from app.core.deps import AuthCtx, DbSession, ReadSession
from app.models.enums import AuditAction
from app.models.user import WorkspaceMember, Workspace
from app.schemas.auth import (
    LoginRequest,
    MeResponse,
    RefreshRequest,
    RegisterRequest,
    TokenPair,
    UserOut,
    WorkspaceSummary,
)
from app.schemas.common import Message
from app.services import audit_service, auth_service, branding_service

router = APIRouter(prefix="/auth", tags=["auth"])


def _meta(request: Request) -> tuple[str | None, str | None]:
    return (
        request.client.host if request.client else None,
        request.headers.get("user-agent"),
    )


@router.post("/register", response_model=TokenPair, status_code=status.HTTP_201_CREATED)
async def register(payload: RegisterRequest, request: Request, db: DbSession) -> TokenPair:
    from app.core.rbac import Role

    # Closed signup (Phase 9): once any workspace exists, only admins create
    # accounts (Team desk). The very first registration stays open so a fresh
    # install can bootstrap itself.
    from app.core.config import settings as app_settings

    if not app_settings.ALLOW_PUBLIC_REGISTRATION:
        existing = (await db.execute(select(Workspace.id).limit(1))).scalar_one_or_none()
        if existing is not None:
            from app.core.errors import PermissionDeniedError

            raise PermissionDeniedError(
                "Sign-up is closed. Ask your admin to create your account from the Team page."
            )

    user, workspace = await auth_service.register(
        db,
        email=payload.email,
        password=payload.password,
        full_name=payload.full_name,
        workspace_name=payload.workspace_name,
    )
    ip, ua = _meta(request)
    tokens = await auth_service.issue_tokens(
        db, user=user, workspace_id=workspace.id, role=Role.ADMIN, user_agent=ua, ip_address=ip
    )
    await db.commit()
    return tokens


@router.post("/login", response_model=TokenPair)
async def login(payload: LoginRequest, request: Request, db: DbSession) -> TokenPair:
    from app.services import login_ip_service

    _ip0, _ua0 = _meta(request)
    pre_ip = login_ip_service.client_ip(request) or _ip0
    user = await auth_service.authenticate(
        db, email=payload.email, password=payload.password,
        ip_address=pre_ip, user_agent=_ua0,
    )
    membership = await auth_service.default_workspace(db, user.id)
    if membership is None:
        await db.commit()
        from app.core.errors import AuthenticationError

        raise AuthenticationError("User has no workspace membership")
    ip, ua = _meta(request)
    # ── Login IP whitelist (owner rule): only whitelisted networks may sign in,
    # with per-user / per-role exemptions (precedence user > role > master).
    # Enforced AFTER credential+membership checks so exemptions can resolve;
    # blocked attempts are audited. Fail-open on internal errors — a broken
    # rules row must never lock the whole company out.
    real_ip = login_ip_service.client_ip(request) or ip
    try:
        rules = await login_ip_service.get_rules(db)
        team_mode = await login_ip_service.resolve_team_mode(db, rules, user.id)
        allowed, why = login_ip_service.is_allowed(
            rules, real_ip, user.id, membership.role.value, team_mode=team_mode
        )
    except Exception:  # noqa: BLE001
        allowed, why = True, "rules unavailable (fail-open)"
    if not allowed:
        await audit_service.record(
            db, action=AuditAction.LOGIN_FAILED, actor_user_id=user.id,
            workspace_id=membership.workspace_id,
            summary=f"Login blocked by IP whitelist ({real_ip}: {why})",
            ip_address=real_ip, user_agent=ua,
        )
        await db.commit()
        from app.core.errors import PermissionDeniedError

        raise PermissionDeniedError(
            "Sign-in from this network isn't allowed. Ask your admin to whitelist your IP "
            "(Settings → Security)."
        )
    ip = real_ip  # audit/token metadata records the REAL client IP, not the proxy's
    tokens = await auth_service.issue_tokens(
        db, user=user, workspace_id=membership.workspace_id, role=membership.role,
        user_agent=ua, ip_address=ip,
    )
    await audit_service.record(
        db, action=AuditAction.LOGIN, actor_user_id=user.id,
        workspace_id=membership.workspace_id, summary="Login", ip_address=ip, user_agent=ua,
    )
    await db.commit()
    return tokens


@router.post("/refresh", response_model=TokenPair)
async def refresh(payload: RefreshRequest, request: Request, db: DbSession) -> TokenPair:
    from app.services import login_ip_service

    ip = login_ip_service.client_ip(request)
    ua = request.headers.get("user-agent")
    try:
        bind = bool((await login_ip_service.get_rules(db)).get("bind_sessions"))
    except Exception:  # noqa: BLE001 — never let a rules problem kill refresh
        bind = False
    tokens = await auth_service.rotate_refresh(
        db, refresh_token=payload.refresh_token,
        ip_address=ip, user_agent=ua, enforce_ip_bind=bind,
    )
    await db.commit()
    return tokens


@router.post("/logout", response_model=Message)
async def logout(payload: RefreshRequest, request: Request, db: DbSession) -> Message:
    from app.services import login_ip_service

    await auth_service.logout(
        db, refresh_token=payload.refresh_token,
        ip_address=login_ip_service.client_ip(request),
        user_agent=request.headers.get("user-agent"),
    )
    await db.commit()
    return Message(message="Logged out")


@router.get("/me", response_model=MeResponse)
async def me(ctx: AuthCtx, db: ReadSession) -> MeResponse:
    rows = (
        await db.execute(
            select(WorkspaceMember, Workspace)
            .join(Workspace, Workspace.id == WorkspaceMember.workspace_id)
            .where(WorkspaceMember.user_id == ctx.user.id)
        )
    ).all()
    workspaces = [
        WorkspaceSummary(id=ws.id, name=ws.name, slug=ws.slug, role=member.role.value)
        for member, ws in rows
    ]
    # Display preferences ride the branding Setting (admin-managed) — the whole
    # UI reads them from the already-cached /auth/me, zero extra requests.
    branding = await branding_service.get_branding(db, ctx.workspace_id) if ctx.workspace_id else {}
    return MeResponse(
        user=UserOut.model_validate(ctx.user),
        workspaces=workspaces,
        active_workspace_id=ctx.workspace_id,
        role=ctx.role.value,
        prefs={"show_avatars": bool(branding.get("show_avatars", True))},
    )


class BrandingOut(BaseModel):
    company_name: str | None = None
    logo_data_uri: str | None = None
    logo_dark_data_uri: str | None = None
    # Phase 10 P8 — safe additions only (never company_domain):
    announcement: str | None = None      # admin-controlled login-page banner
    smtp_ready: bool = False             # forgot-password shows only when true


@router.get("/branding", response_model=BrandingOut)
async def branding(db: ReadSession) -> BrandingOut:
    """Login-screen branding (company name + logo). Intentionally public —
    it renders before anyone can authenticate — and returns only the safe
    subset (never ``company_domain``)."""
    from app.integrations import mailer

    data = await branding_service.public_branding(db)
    data["smtp_ready"] = mailer.smtp_configured()
    return BrandingOut(**data)


# ── Self-serve password reset (Phase 10 P8; needs SMTP) ─────────────────────────
class ForgotPasswordRequest(BaseModel):
    email: str


class ResetPasswordRequest(BaseModel):
    token: str
    new_password: str


@router.post("/forgot-password", response_model=Message)
async def forgot_password(payload: ForgotPasswordRequest, db: DbSession) -> Message:
    """ALWAYS answers OK (anti-enumeration). When the account exists, is active,
    and SMTP is configured, a one-time reset code is emailed (only its sha256
    hash is stored; TTL = PASSWORD_RESET_TTL_MINUTES)."""
    import asyncio
    import hashlib
    import secrets
    from datetime import datetime, timedelta, timezone

    from app.core.config import settings as _settings
    from app.integrations import mailer
    from app.models.user import PasswordResetToken, User

    ok = Message(message="If that account exists, a reset code has been emailed.")
    if not mailer.smtp_configured():
        return ok
    user = (
        await db.execute(select(User).where(User.email == payload.email.strip().lower()))
    ).scalar_one_or_none()
    if user is None or not user.is_active:
        return ok
    raw = secrets.token_urlsafe(32)
    db.add(
        PasswordResetToken(
            user_id=user.id,
            token_hash=hashlib.sha256(raw.encode()).hexdigest(),
            expires_at=datetime.now(timezone.utc)
            + timedelta(minutes=_settings.PASSWORD_RESET_TTL_MINUTES),
        )
    )
    await db.commit()
    branding_data = await branding_service.public_branding(db)
    company = branding_data.get("company_name") or "LinkSentinel"
    body = (
        f"A password reset was requested for your {company} account.\n"
        f"Your reset code (valid {_settings.PASSWORD_RESET_TTL_MINUTES} minutes):\n\n{raw}\n\n"
        'Open the login page, choose "Forgot password", and paste the code.\n'
        "If you didn't request this, ignore this email."
    )
    try:
        await asyncio.to_thread(
            mailer.send_email, user.email, f"{company} password reset", body,
            mailer.branded_html(company, body),
        )
    except Exception:  # noqa: BLE001 — same OK either way (anti-enumeration)
        pass
    return ok


@router.post("/reset-password", response_model=Message)
async def reset_password(payload: ResetPasswordRequest, db: DbSession) -> Message:
    """Redeem a one-time reset code: sets the new password, burns the code, and
    revokes the user's refresh tokens (every session must log in again)."""
    import asyncio
    import hashlib
    from datetime import datetime, timezone

    from app.core.errors import ValidationAppError
    from app.core.security import hash_password
    from app.models.user import PasswordResetToken, User

    if len(payload.new_password) < 8:
        raise ValidationAppError("Password must be at least 8 characters.")
    token_hash = hashlib.sha256(payload.token.strip().encode()).hexdigest()
    prt = (
        await db.execute(
            select(PasswordResetToken).where(PasswordResetToken.token_hash == token_hash)
        )
    ).scalar_one_or_none()
    now = datetime.now(timezone.utc)
    if prt is None or prt.used_at is not None or prt.expires_at < now:
        raise ValidationAppError("This reset code is invalid or has expired.")
    user = await db.get(User, prt.user_id)
    if user is None or not user.is_active:
        raise ValidationAppError("This reset code is invalid or has expired.")
    user.password_hash = await asyncio.to_thread(hash_password, payload.new_password)
    user.failed_login_attempts = 0
    user.locked_until = None
    prt.used_at = now
    await auth_service._revoke_user_tokens(db, user.id)  # every session re-logs-in
    await audit_service.record(
        db, action=AuditAction.UPDATE, workspace_id=None, actor_user_id=user.id,
        entity_type="user", entity_id=user.id, summary="Password reset via emailed code",
    )
    await db.commit()
    return Message(message="Password updated — you can sign in now.")


# ── Self-service account settings (delivery-polish T2): photo + password ─────
class ChangePasswordRequest(BaseModel):
    current_password: str
    new_password: str


@router.post("/change-password", response_model=Message)
async def change_password(payload: ChangePasswordRequest, ctx: AuthCtx, db: DbSession) -> Message:
    """Logged-in password change: proves the CURRENT password, then swaps the
    hash. Sessions stay valid (the user just proved ownership) — unlike the
    emailed-code reset, which revokes everything."""
    import asyncio

    from app.core.errors import ValidationAppError
    from app.core.security import hash_password, verify_password
    from app.models.user import User

    if len(payload.new_password) < 8:
        raise ValidationAppError("The new password must be at least 8 characters.")
    ok = await asyncio.to_thread(verify_password, payload.current_password, ctx.user.password_hash)
    if not ok:
        raise ValidationAppError("Current password is incorrect.")
    user = await db.get(User, ctx.user.id)
    user.password_hash = await asyncio.to_thread(hash_password, payload.new_password)
    await audit_service.record(
        db, action=AuditAction.UPDATE, workspace_id=ctx.workspace_id, actor_user_id=ctx.user.id,
        entity_type="user", entity_id=ctx.user.id, summary="Password changed (self-service)",
    )
    await db.commit()
    return Message(message="Password changed.")


class AvatarRequest(BaseModel):
    # data:image/... URI or null to remove. ~300KB binary ≈ 400k chars base64.
    avatar_data_uri: str | None = None


@router.put("/avatar", response_model=Message)
async def set_avatar(payload: AvatarRequest, ctx: AuthCtx, db: DbSession) -> Message:
    """Set or clear the signed-in user's profile photo (small data-URI, same
    pattern as the branding logo — no file storage involved)."""
    from app.core.errors import ValidationAppError
    from app.models.user import User

    uri = (payload.avatar_data_uri or "").strip() or None
    if uri is not None:
        if not uri.startswith("data:image/"):
            raise ValidationAppError("The photo must be an image (data:image/... URI).")
        if len(uri) > 400_000:
            raise ValidationAppError("The photo is too large — keep it under ~300 KB.")
    user = await db.get(User, ctx.user.id)
    user.avatar_data_uri = uri
    await db.commit()
    return Message(message="Photo updated." if uri else "Photo removed.")
