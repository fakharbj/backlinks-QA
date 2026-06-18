"""Team & workspace-user management endpoints (Admin / ``MANAGE_USERS``).

Surfaces the RBAC model the rest of the system already enforces: list members,
invite a user into the workspace with a role, change roles, activate/deactivate,
and remove. Every mutation is audit-logged.
"""

from __future__ import annotations

import uuid

from fastapi import APIRouter, Depends, status

from app.core.deps import AuthContext, DbSession, ReadSession, require
from app.core.rbac import Permission
from app.models.enums import AuditAction
from app.models.user import User, WorkspaceMember
from app.schemas.common import Message
from app.schemas.team import TeamActiveUpdate, TeamInvite, TeamMemberOut, TeamRoleUpdate
from app.services import audit_service, team_service

router = APIRouter(prefix="/team", tags=["team"])


def _out(member: WorkspaceMember, user: User) -> TeamMemberOut:
    return TeamMemberOut(
        user_id=user.id,
        email=user.email,
        full_name=user.full_name,
        role=member.role,
        is_active=user.is_active,
        last_login_at=user.last_login_at,
        member_since=member.created_at,
    )


@router.get("/members", response_model=list[TeamMemberOut])
async def list_members(
    db: ReadSession, ctx: AuthContext = Depends(require(Permission.MANAGE_USERS))
) -> list[TeamMemberOut]:
    return [_out(member, user) for member, user in await team_service.list_members(db, ctx)]


@router.post("/members", response_model=TeamMemberOut, status_code=status.HTTP_201_CREATED)
async def invite_member(
    payload: TeamInvite,
    db: DbSession,
    ctx: AuthContext = Depends(require(Permission.MANAGE_USERS)),
) -> TeamMemberOut:
    member, user = await team_service.invite_member(
        db,
        ctx,
        email=payload.email,
        full_name=payload.full_name,
        role=payload.role,
        password=payload.password,
    )
    await audit_service.record(
        db,
        action=AuditAction.CREATE,
        actor_user_id=ctx.user.id,
        workspace_id=ctx.workspace_id,
        entity_type="user",
        entity_id=user.id,
        summary=f"Invited {user.email} as {payload.role.value}",
    )
    await db.commit()
    return _out(member, user)


@router.patch("/members/{user_id}", response_model=TeamMemberOut)
async def update_member_role(
    user_id: uuid.UUID,
    payload: TeamRoleUpdate,
    db: DbSession,
    ctx: AuthContext = Depends(require(Permission.MANAGE_USERS)),
) -> TeamMemberOut:
    member, user = await team_service.update_role(db, ctx, user_id, payload.role)
    await audit_service.record(
        db,
        action=AuditAction.UPDATE,
        actor_user_id=ctx.user.id,
        workspace_id=ctx.workspace_id,
        entity_type="user",
        entity_id=user_id,
        summary=f"Changed role of {user.email} to {payload.role.value}",
    )
    await db.commit()
    return _out(member, user)


@router.post("/members/{user_id}/active", response_model=TeamMemberOut)
async def set_member_active(
    user_id: uuid.UUID,
    payload: TeamActiveUpdate,
    db: DbSession,
    ctx: AuthContext = Depends(require(Permission.MANAGE_USERS)),
) -> TeamMemberOut:
    member, user = await team_service.set_active(db, ctx, user_id, payload.is_active)
    await audit_service.record(
        db,
        action=AuditAction.UPDATE,
        actor_user_id=ctx.user.id,
        workspace_id=ctx.workspace_id,
        entity_type="user",
        entity_id=user_id,
        summary=f"{'Activated' if payload.is_active else 'Deactivated'} {user.email}",
    )
    await db.commit()
    return _out(member, user)


@router.delete("/members/{user_id}", response_model=Message)
async def remove_member(
    user_id: uuid.UUID,
    db: DbSession,
    ctx: AuthContext = Depends(require(Permission.MANAGE_USERS)),
) -> Message:
    await team_service.remove_member(db, ctx, user_id)
    await audit_service.record(
        db,
        action=AuditAction.DELETE,
        actor_user_id=ctx.user.id,
        workspace_id=ctx.workspace_id,
        entity_type="user",
        entity_id=user_id,
        summary="Removed member from workspace",
    )
    await db.commit()
    return Message(message="Member removed")
