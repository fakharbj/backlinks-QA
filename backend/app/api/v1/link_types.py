"""Link-type catalog endpoints (Phase 8). Read for members; manage = Manager+."""

from __future__ import annotations

import uuid

from fastapi import APIRouter, Depends

from app.core.deps import AuthContext, AuthCtx, DbSession, ReadSession, require_role
from app.core.rbac import Role
from app.models.enums import AuditAction
from app.schemas.link_type import LinkTypeCreate, LinkTypeOut, LinkTypeUpdate
from app.services import audit_service
from app.services import link_type_service as svc

router = APIRouter(prefix="/link-types", tags=["link-types"])


@router.get("", response_model=list[LinkTypeOut])
async def list_link_types(ctx: AuthCtx, db: ReadSession) -> list[LinkTypeOut]:
    return [LinkTypeOut(**row) for row in await svc.list_types(db, ctx)]


@router.post("", response_model=LinkTypeOut, status_code=201)
async def create_link_type(
    payload: LinkTypeCreate, db: DbSession,
    ctx: AuthContext = Depends(require_role(Role.MANAGER)),
) -> LinkTypeOut:
    lt = await svc.create_type(db, ctx, payload.name, payload.color, payload.description)
    await audit_service.record(
        db, action=AuditAction.CREATE, actor_user_id=ctx.user.id, workspace_id=ctx.workspace_id,
        entity_type="link_type", entity_id=lt.id, summary=f"Created link type {lt.name}",
    )
    await db.commit()
    return LinkTypeOut(
        id=lt.id, name=lt.name, slug=lt.slug, color=lt.color,
        description=lt.description, is_active=lt.is_active,
    )


@router.patch("/{type_id}", response_model=LinkTypeOut)
async def update_link_type(
    type_id: uuid.UUID, payload: LinkTypeUpdate, db: DbSession,
    ctx: AuthContext = Depends(require_role(Role.MANAGER)),
) -> LinkTypeOut:
    lt = await svc.update_type(db, ctx, type_id, payload)
    await audit_service.record(
        db, action=AuditAction.UPDATE, actor_user_id=ctx.user.id, workspace_id=ctx.workspace_id,
        entity_type="link_type", entity_id=lt.id, summary=f"Updated link type {lt.name}",
    )
    await db.commit()
    return LinkTypeOut(
        id=lt.id, name=lt.name, slug=lt.slug, color=lt.color,
        description=lt.description, is_active=lt.is_active,
    )


@router.delete("/{type_id}")
async def delete_link_type(
    type_id: uuid.UUID, db: DbSession,
    ctx: AuthContext = Depends(require_role(Role.MANAGER)),
) -> dict:
    await svc.delete_type(db, ctx, type_id)
    await audit_service.record(
        db, action=AuditAction.DELETE, actor_user_id=ctx.user.id, workspace_id=ctx.workspace_id,
        entity_type="link_type", entity_id=type_id, summary="Deleted link type",
    )
    await db.commit()
    return {"ok": True}
