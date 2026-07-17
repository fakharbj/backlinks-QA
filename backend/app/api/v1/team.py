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


# ── TeamLead member assignments (Phase 9) ────────────────────────────────────
from pydantic import BaseModel, Field  # noqa: E402


class TeamLeadLabels(BaseModel):
    manager_user_id: uuid.UUID
    labels: list[str]


@router.get("/leads")
async def list_teamlead_assignments(
    db: ReadSession, ctx: AuthContext = Depends(require(Permission.MANAGE_USERS))
) -> list[dict]:
    from sqlalchemy import select

    from app.models.workforce import TeamLeadAssignment

    rows = (
        await db.execute(
            select(TeamLeadAssignment).where(
                TeamLeadAssignment.workspace_id == ctx.workspace_id
            )
        )
    ).scalars().all()
    grouped: dict[str, list[str]] = {}
    for r in rows:
        grouped.setdefault(str(r.manager_user_id), []).append(r.member_label)
    return [{"manager_user_id": k, "labels": sorted(v)} for k, v in grouped.items()]


@router.put("/leads", response_model=Message)
async def set_teamlead_assignments(
    payload: TeamLeadLabels, db: DbSession,
    ctx: AuthContext = Depends(require(Permission.MANAGE_USERS)),
) -> Message:
    """Replace the set of member labels a TeamLead oversees (empty list = sees all)."""
    from sqlalchemy import delete as sa_delete

    from app.models.workforce import TeamLeadAssignment

    await db.execute(
        sa_delete(TeamLeadAssignment).where(
            TeamLeadAssignment.workspace_id == ctx.workspace_id,
            TeamLeadAssignment.manager_user_id == payload.manager_user_id,
        )
    )
    labels = sorted({l.strip()[:200] for l in payload.labels if l.strip()})
    for label in labels[:100]:
        db.add(
            TeamLeadAssignment(
                workspace_id=ctx.workspace_id,
                manager_user_id=payload.manager_user_id,
                member_label=label,
            )
        )
    await audit_service.record(
        db, action=AuditAction.UPDATE, actor_user_id=ctx.user.id, workspace_id=ctx.workspace_id,
        entity_type="teamlead_users", entity_id=payload.manager_user_id,
        summary=f"TeamLead now oversees {len(labels)} member(s)",
    )
    await db.commit()
    return Message(message=f"Saved — this team lead now sees {len(labels) or 'ALL'} member(s)")


class MemberProjects(BaseModel):
    project_ids: list[uuid.UUID]


@router.get("/members/{user_id}/projects")
async def get_member_projects(
    user_id: uuid.UUID, db: ReadSession,
    ctx: AuthContext = Depends(require(Permission.MANAGE_USERS)),
) -> dict:
    """The projects a member is scoped to. Empty = TeamLead/QA see all projects;
    a Viewer with no rows sees none (Viewers must be explicitly scoped)."""
    from sqlalchemy import select

    from app.models.project import Project, ProjectMember

    rows = (
        await db.execute(
            select(ProjectMember.project_id)
            .join(Project, Project.id == ProjectMember.project_id)
            .where(Project.workspace_id == ctx.workspace_id, ProjectMember.user_id == user_id)
        )
    ).scalars().all()
    return {"project_ids": [str(r) for r in rows]}


@router.put("/members/{user_id}/projects", response_model=Message)
async def set_member_projects(
    user_id: uuid.UUID, payload: MemberProjects, db: DbSession,
    ctx: AuthContext = Depends(require(Permission.MANAGE_USERS)),
) -> Message:
    """Replace the set of projects a member is scoped to (this workspace only)."""
    from sqlalchemy import delete as sa_delete
    from sqlalchemy import select

    from app.core.errors import NotFoundError, ValidationAppError
    from app.models.project import Project, ProjectMember

    members = await team_service.list_members(db, ctx)
    if not any(u.id == user_id for _, u in members):
        raise NotFoundError("Member not found in this workspace")

    wanted = set(payload.project_ids)
    if wanted:
        valid = set(
            (
                await db.execute(
                    select(Project.id).where(
                        Project.workspace_id == ctx.workspace_id, Project.id.in_(wanted)
                    )
                )
            ).scalars().all()
        )
        if valid != wanted:
            raise ValidationAppError("One or more projects are not in this workspace.")

    ws_project_ids = select(Project.id).where(Project.workspace_id == ctx.workspace_id)
    await db.execute(
        sa_delete(ProjectMember).where(
            ProjectMember.user_id == user_id,
            ProjectMember.project_id.in_(ws_project_ids),
        )
    )
    for pid in wanted:
        db.add(ProjectMember(project_id=pid, user_id=user_id, role=None))
    await audit_service.record(
        db, action=AuditAction.UPDATE, actor_user_id=ctx.user.id, workspace_id=ctx.workspace_id,
        entity_type="project_members", entity_id=user_id,
        summary=f"Member scoped to {len(wanted) or 'ALL (unrestricted)'} project(s)",
    )
    await db.commit()
    return Message(
        message=(
            f"Saved — this member now sees {len(wanted)} project(s)."
            if wanted
            else "Saved — no project restriction (TeamLead/QA see all; Viewers see none)."
        )
    )


@router.post("/members/{user_id}/reset-password")
async def reset_member_password(
    user_id: uuid.UUID, db: DbSession,
    ctx: AuthContext = Depends(require(Permission.MANAGE_USERS)),
) -> dict:
    """Admin password reset: sets a new temporary password and returns it ONCE
    (hand it to the user; they should change it after logging in)."""
    import asyncio
    import secrets

    from app.core.errors import NotFoundError
    from app.core.security import hash_password

    members = await team_service.list_members(db, ctx)
    target = next((u for m, u in members if u.id == user_id), None)
    if target is None:
        raise NotFoundError("Member not found in this workspace")
    temp = f"Reset-{secrets.token_urlsafe(9)}"
    # Argon2 is CPU-heavy — run it off the event loop.
    target.password_hash = await asyncio.to_thread(hash_password, temp)
    await audit_service.record(
        db, action=AuditAction.UPDATE, actor_user_id=ctx.user.id, workspace_id=ctx.workspace_id,
        entity_type="user", entity_id=user_id, summary="Password reset by admin",
    )
    await db.commit()
    return {"temp_password": temp}


# ── Account editing: change a member's login email / display name ────────────
class AccountUpdate(BaseModel):
    email: str | None = Field(default=None, max_length=320)
    full_name: str | None = Field(default=None, max_length=200)


@router.patch("/members/{user_id}/account", response_model=Message)
async def update_member_account(
    user_id: uuid.UUID, payload: AccountUpdate, db: DbSession,
    ctx: AuthContext = Depends(require(Permission.MANAGE_USERS)),
) -> Message:
    """Change a member's login email and/or display name (admin, audited).
    Passwords are never viewable (they're one-way encrypted) — use
    Reset password, which shows a one-time temporary password instead."""
    from sqlalchemy import select as _select

    from app.core.errors import ConflictError, NotFoundError, ValidationAppError
    from app.models.user import User, WorkspaceMember

    member = (
        await db.execute(
            _select(WorkspaceMember).where(
                WorkspaceMember.workspace_id == ctx.workspace_id,
                WorkspaceMember.user_id == user_id,
            )
        )
    ).scalar_one_or_none()
    if member is None:
        raise NotFoundError("Member not found in this workspace")
    user = await db.get(User, user_id)
    if user is None:
        raise NotFoundError("User not found")
    changed: list[str] = []
    if payload.email is not None:
        email = payload.email.strip().lower()
        if not email or "@" not in email:
            raise ValidationAppError("Enter a valid email address.")
        if email != user.email:
            exists = (
                await db.execute(_select(User).where(User.email == email))
            ).scalar_one_or_none()
            if exists is not None:
                raise ConflictError("That email is already used by another account.")
            changed.append(f"email {user.email} → {email}")
            user.email = email
    if payload.full_name is not None and payload.full_name.strip():
        if payload.full_name.strip() != (user.full_name or ""):
            changed.append(f"name → {payload.full_name.strip()}")
            user.full_name = payload.full_name.strip()
    if not changed:
        return Message(message="Nothing to change.")
    await audit_service.record(
        db, action=AuditAction.UPDATE, actor_user_id=ctx.user.id, workspace_id=ctx.workspace_id,
        entity_type="user_account", entity_id=user_id,
        summary=f"Account updated: {'; '.join(changed)}",
    )
    await db.commit()
    return Message(message="Account updated — " + "; ".join(changed))
