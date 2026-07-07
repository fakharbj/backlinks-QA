"""Company Gmail account tracking (Tranche H).

Workspace catalog of shared Gmail addresses + their assignment history to
users/projects. Reads need VIEW_DASHBOARDS; account CRUD needs MANAGE_USERS;
assigning/revoking needs ASSIGN_MEMBERS (admin+manager). No live Gmail feed —
this is managed assignment + a manual ``last_used`` signal. All mutations audited.
"""

from __future__ import annotations

import uuid

from fastapi import APIRouter, Depends, Query
from pydantic import BaseModel, Field

from app.core.deps import AuthContext, AuthCtx, DbSession, ReadSession, require
from app.core.rbac import Permission
from app.models.enums import AuditAction
from app.services import audit_service, gmail_service

router = APIRouter(prefix="/gmail", tags=["gmail"])


class AccountCreate(BaseModel):
    email: str = Field(min_length=3, max_length=320)
    display_name: str | None = Field(default=None, max_length=200)
    notes: str | None = Field(default=None, max_length=2000)


class AccountPatch(BaseModel):
    display_name: str | None = None
    notes: str | None = None
    status: str | None = None
    is_active: bool | None = None


class AssignIn(BaseModel):
    account_id: uuid.UUID
    scope: str  # user | project
    user_id: uuid.UUID | None = None
    project_id: uuid.UUID | None = None
    notes: str | None = Field(default=None, max_length=2000)


@router.get("/accounts")
async def list_accounts(
    ctx: AuthCtx, db: ReadSession, include_retired: bool = Query(False)
) -> list[dict]:
    return await gmail_service.list_accounts(db, ctx, include_retired=include_retired)


@router.post("/accounts")
async def create_account(
    payload: AccountCreate, db: DbSession,
    ctx: AuthContext = Depends(require(Permission.MANAGE_USERS)),
) -> dict:
    acc = await gmail_service.create_account(
        db, ctx, email=payload.email, display_name=payload.display_name, notes=payload.notes
    )
    await audit_service.record(
        db, action=AuditAction.CREATE, actor_user_id=ctx.user.id, workspace_id=ctx.workspace_id,
        entity_type="gmail_account", entity_id=acc["id"], summary=f"Added Gmail {acc['email']}",
    )
    await db.commit()
    return acc


@router.patch("/accounts/{account_id}")
async def update_account(
    account_id: uuid.UUID, payload: AccountPatch, db: DbSession,
    ctx: AuthContext = Depends(require(Permission.MANAGE_USERS)),
) -> dict:
    acc = await gmail_service.update_account(
        db, ctx, account_id, patch=payload.model_dump(exclude_unset=True)
    )
    await audit_service.record(
        db, action=AuditAction.UPDATE, actor_user_id=ctx.user.id, workspace_id=ctx.workspace_id,
        entity_type="gmail_account", entity_id=account_id, summary=f"Updated Gmail {acc['email']}",
    )
    await db.commit()
    return acc


@router.delete("/accounts/{account_id}")
async def retire_account(
    account_id: uuid.UUID, db: DbSession,
    ctx: AuthContext = Depends(require(Permission.MANAGE_USERS)),
) -> dict:
    result = await gmail_service.retire_account(db, ctx, account_id)
    await audit_service.record(
        db, action=AuditAction.DELETE, actor_user_id=ctx.user.id, workspace_id=ctx.workspace_id,
        entity_type="gmail_account", entity_id=account_id, summary=result["message"],
    )
    await db.commit()
    return result


@router.post("/accounts/{account_id}/used")
async def mark_used(
    account_id: uuid.UUID, db: DbSession,
    ctx: AuthContext = Depends(require(Permission.ASSIGN_MEMBERS)),
) -> dict:
    acc = await gmail_service.mark_used(db, ctx, account_id)
    await db.commit()
    return acc


@router.post("/assign")
async def assign(
    payload: AssignIn, db: DbSession,
    ctx: AuthContext = Depends(require(Permission.ASSIGN_MEMBERS)),
) -> dict:
    result = await gmail_service.assign(
        db, ctx, account_id=payload.account_id, scope=payload.scope,
        user_id=payload.user_id, project_id=payload.project_id, notes=payload.notes,
        actor_id=ctx.user.id,
    )
    await audit_service.record(
        db, action=AuditAction.UPDATE, actor_user_id=ctx.user.id, workspace_id=ctx.workspace_id,
        entity_type="gmail_assignment", entity_id=result["id"], summary=result["message"],
    )
    await db.commit()
    return result


@router.post("/assignments/{assignment_id}/revoke")
async def revoke(
    assignment_id: uuid.UUID, db: DbSession,
    ctx: AuthContext = Depends(require(Permission.ASSIGN_MEMBERS)),
) -> dict:
    result = await gmail_service.revoke(db, ctx, assignment_id)
    await audit_service.record(
        db, action=AuditAction.UPDATE, actor_user_id=ctx.user.id, workspace_id=ctx.workspace_id,
        entity_type="gmail_assignment", entity_id=assignment_id, summary="Revoked Gmail assignment",
    )
    await db.commit()
    return result


@router.get("/by-user/{user_id}")
async def by_user(user_id: uuid.UUID, ctx: AuthCtx, db: ReadSession) -> list[dict]:
    return await gmail_service.for_user(db, ctx, user_id)


@router.get("/by-project/{project_id}")
async def by_project(project_id: uuid.UUID, ctx: AuthCtx, db: ReadSession) -> list[dict]:
    return await gmail_service.for_project(db, ctx, project_id)
