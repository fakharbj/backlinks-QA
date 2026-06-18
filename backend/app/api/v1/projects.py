"""Project, vendor, and campaign endpoints."""

from __future__ import annotations

import uuid

from fastapi import APIRouter, Depends, status

from app.core.deps import AuthContext, AuthCtx, DbSession, ReadSession, require
from app.core.rbac import Permission
from app.models.enums import AuditAction
from app.schemas.common import Message
from app.schemas.project import (
    CampaignCreate,
    CampaignOut,
    ProjectCreate,
    ProjectMemberAdd,
    ProjectOut,
    ProjectUpdate,
    VendorCreate,
    VendorOut,
)
from app.services import audit_service, project_service

router = APIRouter(tags=["projects"])


@router.get("/projects", response_model=list[ProjectOut])
async def list_projects(ctx: AuthCtx, db: ReadSession) -> list[ProjectOut]:
    projects = await project_service.list_projects(db, ctx)
    return [ProjectOut.model_validate(p) for p in projects]


@router.post("/projects", response_model=ProjectOut, status_code=status.HTTP_201_CREATED)
async def create_project(
    payload: ProjectCreate, db: DbSession, ctx: AuthContext = Depends(require(Permission.CREATE_PROJECT))
) -> ProjectOut:
    project = await project_service.create_project(db, ctx, payload)
    await audit_service.record(
        db, action=AuditAction.CREATE, actor_user_id=ctx.user.id, workspace_id=ctx.workspace_id,
        entity_type="project", entity_id=project.id, summary=f"Created project {project.name}",
    )
    await db.commit()
    return ProjectOut.model_validate(project)


@router.get("/projects/{project_id}", response_model=ProjectOut)
async def get_project(project_id: uuid.UUID, ctx: AuthCtx, db: ReadSession) -> ProjectOut:
    project = await project_service.get_project(db, ctx, project_id)
    return ProjectOut.model_validate(project)


@router.patch("/projects/{project_id}", response_model=ProjectOut)
async def update_project(
    project_id: uuid.UUID, payload: ProjectUpdate, db: DbSession,
    ctx: AuthContext = Depends(require(Permission.EDIT_PROJECT)),
) -> ProjectOut:
    project = await project_service.update_project(db, ctx, project_id, payload)
    await audit_service.record(
        db, action=AuditAction.UPDATE, actor_user_id=ctx.user.id, workspace_id=ctx.workspace_id,
        entity_type="project", entity_id=project_id, summary="Updated project",
    )
    await db.commit()
    return ProjectOut.model_validate(project)


@router.delete("/projects/{project_id}", response_model=Message)
async def delete_project(
    project_id: uuid.UUID, db: DbSession,
    ctx: AuthContext = Depends(require(Permission.DELETE_PROJECT)),
) -> Message:
    await project_service.delete_project(db, ctx, project_id)
    await audit_service.record(
        db, action=AuditAction.DELETE, actor_user_id=ctx.user.id, workspace_id=ctx.workspace_id,
        entity_type="project", entity_id=project_id, summary="Deleted project",
    )
    await db.commit()
    return Message(message="Project deleted")


@router.post("/projects/{project_id}/members", response_model=Message)
async def add_member(
    project_id: uuid.UUID, payload: ProjectMemberAdd, db: DbSession,
    ctx: AuthContext = Depends(require(Permission.ASSIGN_MEMBERS)),
) -> Message:
    await project_service.add_member(db, ctx, project_id, payload.user_id, payload.role)
    await db.commit()
    return Message(message="Member added")


# ── Vendors ─────────────────────────────────────────────────────────────────────
@router.get("/vendors", response_model=list[VendorOut])
async def list_vendors(ctx: AuthCtx, db: ReadSession) -> list[VendorOut]:
    return [VendorOut.model_validate(v) for v in await project_service.list_vendors(db, ctx)]


@router.post("/vendors", response_model=VendorOut, status_code=status.HTTP_201_CREATED)
async def create_vendor(
    payload: VendorCreate, db: DbSession,
    ctx: AuthContext = Depends(require(Permission.MANAGE_VENDORS)),
) -> VendorOut:
    vendor = await project_service.create_vendor(db, ctx, payload)
    await db.commit()
    return VendorOut.model_validate(vendor)


# ── Campaigns ────────────────────────────────────────────────────────────────────
@router.get("/campaigns", response_model=list[CampaignOut])
async def list_campaigns(
    ctx: AuthCtx, db: ReadSession, project_id: uuid.UUID | None = None
) -> list[CampaignOut]:
    items = await project_service.list_campaigns(db, ctx, project_id)
    return [CampaignOut.model_validate(c) for c in items]


@router.post("/campaigns", response_model=CampaignOut, status_code=status.HTTP_201_CREATED)
async def create_campaign(
    payload: CampaignCreate, db: DbSession,
    ctx: AuthContext = Depends(require(Permission.MANAGE_VENDORS)),
) -> CampaignOut:
    campaign = await project_service.create_campaign(db, ctx, payload)
    await db.commit()
    return CampaignOut.model_validate(campaign)
