"""Workspace team & user management (PRD §5): list / invite / role / activate / remove.

Every operation is workspace-scoped and gated on ``MANAGE_USERS`` (Admin) at the
router. Service-layer guard-rails prevent a workspace from locking itself out:
the last Admin cannot be demoted, deactivated, or removed, and a user cannot
deactivate or remove their own account.
"""

from __future__ import annotations

import uuid

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.deps import AuthContext
from app.core.errors import ConflictError, NotFoundError, ValidationAppError
from app.core.rbac import Role
from app.core.security import hash_password
from app.models.user import User, WorkspaceMember


async def list_members(db: AsyncSession, ctx: AuthContext) -> list[tuple[WorkspaceMember, User]]:
    rows = (
        await db.execute(
            select(WorkspaceMember, User)
            .join(User, User.id == WorkspaceMember.user_id)
            .where(WorkspaceMember.workspace_id == ctx.workspace_id)
            .order_by(WorkspaceMember.role, User.full_name)
        )
    ).all()
    return [(member, user) for member, user in rows]


async def invite_member(
    db: AsyncSession,
    ctx: AuthContext,
    *,
    email: str,
    full_name: str,
    role: Role,
    password: str,
) -> tuple[WorkspaceMember, User]:
    """Add a user to the active workspace, creating the account if new."""
    email = email.strip().lower()
    user = (await db.execute(select(User).where(User.email == email))).scalar_one_or_none()
    if user is None:
        user = User(
            email=email,
            full_name=full_name.strip(),
            password_hash=hash_password(password),
            is_active=True,
        )
        db.add(user)
        await db.flush()
    elif await _is_member(db, ctx.workspace_id, user.id):
        raise ConflictError("User is already a member of this workspace")

    member = WorkspaceMember(
        workspace_id=ctx.workspace_id,
        user_id=user.id,
        role=role,
        invited_by=ctx.user.id,
    )
    db.add(member)
    await db.flush()
    return member, user


async def update_role(
    db: AsyncSession, ctx: AuthContext, user_id: uuid.UUID, role: Role
) -> tuple[WorkspaceMember, User]:
    member = await _membership(db, ctx, user_id)
    if member.role is Role.ADMIN and role is not Role.ADMIN and await _admin_count(db, ctx) <= 1:
        raise ValidationAppError("Cannot demote the last admin of the workspace")
    member.role = role
    await db.flush()
    return member, await _user(db, user_id)


async def set_active(
    db: AsyncSession, ctx: AuthContext, user_id: uuid.UUID, active: bool
) -> tuple[WorkspaceMember, User]:
    member = await _membership(db, ctx, user_id)
    if user_id == ctx.user.id and not active:
        raise ValidationAppError("You cannot deactivate your own account")
    if not active and member.role is Role.ADMIN and await _admin_count(db, ctx) <= 1:
        raise ValidationAppError("Cannot deactivate the last admin of the workspace")
    user = await _user(db, user_id)
    user.is_active = active
    await db.flush()
    return member, user


async def remove_member(db: AsyncSession, ctx: AuthContext, user_id: uuid.UUID) -> None:
    member = await _membership(db, ctx, user_id)
    if user_id == ctx.user.id:
        raise ValidationAppError("You cannot remove yourself from the workspace")
    if member.role is Role.ADMIN and await _admin_count(db, ctx) <= 1:
        raise ValidationAppError("Cannot remove the last admin of the workspace")
    await db.delete(member)


# ── helpers ─────────────────────────────────────────────────────────────────────
async def _membership(db: AsyncSession, ctx: AuthContext, user_id: uuid.UUID) -> WorkspaceMember:
    member = (
        await db.execute(
            select(WorkspaceMember).where(
                WorkspaceMember.workspace_id == ctx.workspace_id,
                WorkspaceMember.user_id == user_id,
            )
        )
    ).scalar_one_or_none()
    if member is None:
        raise NotFoundError("Team member not found")
    return member


async def _is_member(db: AsyncSession, workspace_id: uuid.UUID, user_id: uuid.UUID) -> bool:
    return (
        await db.execute(
            select(WorkspaceMember.id).where(
                WorkspaceMember.workspace_id == workspace_id,
                WorkspaceMember.user_id == user_id,
            )
        )
    ).scalar_one_or_none() is not None


async def _admin_count(db: AsyncSession, ctx: AuthContext) -> int:
    return int(
        (
            await db.execute(
                select(func.count(WorkspaceMember.id)).where(
                    WorkspaceMember.workspace_id == ctx.workspace_id,
                    WorkspaceMember.role == Role.ADMIN,
                )
            )
        ).scalar_one()
    )


async def _user(db: AsyncSession, user_id: uuid.UUID) -> User:
    user = await db.get(User, user_id)
    if user is None:
        raise NotFoundError("User not found")
    return user
