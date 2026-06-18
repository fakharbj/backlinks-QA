"""Auth endpoints: register, login, refresh, logout, me."""

from __future__ import annotations

from fastapi import APIRouter, Request, status
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
from app.services import audit_service, auth_service

router = APIRouter(prefix="/auth", tags=["auth"])


def _meta(request: Request) -> tuple[str | None, str | None]:
    return (
        request.client.host if request.client else None,
        request.headers.get("user-agent"),
    )


@router.post("/register", response_model=TokenPair, status_code=status.HTTP_201_CREATED)
async def register(payload: RegisterRequest, request: Request, db: DbSession) -> TokenPair:
    from app.core.rbac import Role

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
    user = await auth_service.authenticate(db, email=payload.email, password=payload.password)
    membership = await auth_service.default_workspace(db, user.id)
    if membership is None:
        await db.commit()
        from app.core.errors import AuthenticationError

        raise AuthenticationError("User has no workspace membership")
    ip, ua = _meta(request)
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
async def refresh(payload: RefreshRequest, db: DbSession) -> TokenPair:
    tokens = await auth_service.rotate_refresh(db, refresh_token=payload.refresh_token)
    await db.commit()
    return tokens


@router.post("/logout", response_model=Message)
async def logout(payload: RefreshRequest, db: DbSession) -> Message:
    await auth_service.logout(db, refresh_token=payload.refresh_token)
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
    return MeResponse(
        user=UserOut.model_validate(ctx.user),
        workspaces=workspaces,
        active_workspace_id=ctx.workspace_id,
        role=ctx.role.value,
    )
