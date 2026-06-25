"""Project settings + main domain endpoints (Phase 8, feature 2).

Reads are available to any member with project access; mutations require
EDIT_PROJECT. Every response returns the full settings + domains so the UI can
re-render from one payload.
"""

from __future__ import annotations

import uuid

from fastapi import APIRouter, Depends

from app.core.deps import AuthContext, AuthCtx, DbSession, require
from app.core.rbac import Permission
from app.models.enums import AuditAction
from app.schemas.project_settings import (
    ProjectDomainCreate,
    ProjectDomainOut,
    ProjectSettingsOut,
    ProjectSettingsUpdate,
)
from app.services import audit_service
from app.services import project_settings_service as svc

router = APIRouter(prefix="/projects", tags=["project-settings"])


def _to_out(settings, domains) -> ProjectSettingsOut:
    return ProjectSettingsOut(
        project_id=settings.project_id,
        scoring_profile=settings.scoring_profile,
        index_expected=settings.index_expected,
        treat_sponsored_as_follow=settings.treat_sponsored_as_follow,
        status_thresholds=settings.status_thresholds or {},
        domains=[
            ProjectDomainOut(id=d.id, domain=d.domain, is_primary=d.is_primary) for d in domains
        ],
    )


@router.get("/{project_id}/settings", response_model=ProjectSettingsOut)
async def get_settings(project_id: uuid.UUID, ctx: AuthCtx, db: DbSession) -> ProjectSettingsOut:
    settings = await svc.get_or_create_settings(db, ctx, project_id)
    domains = await svc.list_domains(db, ctx, project_id)
    await db.commit()
    return _to_out(settings, domains)


@router.put("/{project_id}/settings", response_model=ProjectSettingsOut)
async def update_settings(
    project_id: uuid.UUID, payload: ProjectSettingsUpdate, db: DbSession,
    ctx: AuthContext = Depends(require(Permission.EDIT_PROJECT)),
) -> ProjectSettingsOut:
    settings = await svc.update_settings(db, ctx, project_id, payload)
    await audit_service.record(
        db, action=AuditAction.UPDATE, actor_user_id=ctx.user.id, workspace_id=ctx.workspace_id,
        entity_type="project_settings", entity_id=project_id, summary="Project settings updated",
    )
    domains = await svc.list_domains(db, ctx, project_id)
    await db.commit()
    return _to_out(settings, domains)


@router.post("/{project_id}/domains", response_model=ProjectSettingsOut, status_code=201)
async def add_domain(
    project_id: uuid.UUID, payload: ProjectDomainCreate, db: DbSession,
    ctx: AuthContext = Depends(require(Permission.EDIT_PROJECT)),
) -> ProjectSettingsOut:
    pd = await svc.add_domain(db, ctx, project_id, payload)
    await audit_service.record(
        db, action=AuditAction.UPDATE, actor_user_id=ctx.user.id, workspace_id=ctx.workspace_id,
        entity_type="project_domain", entity_id=pd.id, summary=f"Added main domain {pd.domain}",
    )
    settings = await svc.get_or_create_settings(db, ctx, project_id)
    domains = await svc.list_domains(db, ctx, project_id)
    await db.commit()
    return _to_out(settings, domains)


@router.delete("/{project_id}/domains/{domain_id}", response_model=ProjectSettingsOut)
async def remove_domain(
    project_id: uuid.UUID, domain_id: uuid.UUID, db: DbSession,
    ctx: AuthContext = Depends(require(Permission.EDIT_PROJECT)),
) -> ProjectSettingsOut:
    await svc.remove_domain(db, ctx, project_id, domain_id)
    await audit_service.record(
        db, action=AuditAction.UPDATE, actor_user_id=ctx.user.id, workspace_id=ctx.workspace_id,
        entity_type="project_domain", entity_id=domain_id, summary="Removed main domain",
    )
    settings = await svc.get_or_create_settings(db, ctx, project_id)
    domains = await svc.list_domains(db, ctx, project_id)
    await db.commit()
    return _to_out(settings, domains)


@router.post("/{project_id}/domains/{domain_id}/primary", response_model=ProjectSettingsOut)
async def set_primary(
    project_id: uuid.UUID, domain_id: uuid.UUID, db: DbSession,
    ctx: AuthContext = Depends(require(Permission.EDIT_PROJECT)),
) -> ProjectSettingsOut:
    await svc.set_primary(db, ctx, project_id, domain_id)
    await audit_service.record(
        db, action=AuditAction.UPDATE, actor_user_id=ctx.user.id, workspace_id=ctx.workspace_id,
        entity_type="project_domain", entity_id=domain_id, summary="Set primary main domain",
    )
    settings = await svc.get_or_create_settings(db, ctx, project_id)
    domains = await svc.list_domains(db, ctx, project_id)
    await db.commit()
    return _to_out(settings, domains)
