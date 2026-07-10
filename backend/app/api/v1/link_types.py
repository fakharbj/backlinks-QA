"""Link-type catalog endpoints (Phase 8). Read for members; manage = Manager+."""

from __future__ import annotations

import uuid

from fastapi import APIRouter, Depends

from app.core.deps import AuthContext, AuthCtx, DbSession, ReadSession, require_role
from app.core.rbac import Role
from app.models.enums import AuditAction
from app.schemas.link_type import (
    LinkTypeCreate,
    LinkTypeMergeIn,
    LinkTypeOut,
    LinkTypeRenameIn,
    LinkTypeUpdate,
)
from app.services import audit_service
from app.services import link_type_merge_service as merge_svc
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


# ── Standardization: scan → review → merge/rename (Phase 10 P1) ──────────────


@router.get("/merge-proposal")
async def link_type_merge_proposal(
    ctx_db: ReadSession, ctx: AuthContext = Depends(require_role(Role.MANAGER)),
) -> dict:
    """Scan the catalog and propose duplicate/misspelling groups with a suggested
    master each. Read-only — the admin reviews before merging anything."""
    return await merge_svc.merge_proposal(ctx_db, ctx)


@router.get("/{type_id}/merge-preview")
async def link_type_merge_preview(
    type_id: uuid.UUID, winner_id: uuid.UUID, db: ReadSession,
    ctx: AuthContext = Depends(require_role(Role.MANAGER)),
) -> dict:
    """Dry run: exactly how many rows each store would update."""
    return await merge_svc.merge_preview(db, ctx, type_id, winner_id)


@router.post("/{type_id}/merge")
async def merge_link_type(
    type_id: uuid.UUID, payload: LinkTypeMergeIn, db: DbSession,
    ctx: AuthContext = Depends(require_role(Role.MANAGER)),
) -> dict:
    """Merge this type INTO ``winner_id``. DB half is one transaction; the Google
    tab renames run after commit, per-tab fail-open, and are reported back."""
    result = await merge_svc.merge_types(db, ctx, type_id, payload.winner_id)
    await audit_service.record(
        db, action=AuditAction.UPDATE, actor_user_id=ctx.user.id, workspace_id=ctx.workspace_id,
        entity_type="link_type", entity_id=type_id,
        summary=f"Merged link type \"{result['merged']['name']}\" into \"{result['into']['name']}\"",
        before={"link_type": result["merged"]}, after={"link_type": result["into"], "changed": result["changed"]},
    )
    await db.commit()

    tab_renames: list[dict] = []
    if payload.rename_tabs:
        tab_renames = await merge_svc.apply_sheet_tab_renames(
            db, ctx, result["merged"]["name"], result["into"]["name"]
        )
        await db.commit()
    if result.get("gbp_boundary_crossed"):
        # The GBP substring rules (dedup exclusion, relaxed matching) now cover a
        # different row set — rebuild duplicate groups so verdicts stay coherent.
        try:
            from app.services import conflict_service

            await conflict_service.rebuild_workspace(db, ctx.workspace_id)
            await db.commit()
        except Exception:  # noqa: BLE001 - best-effort; log path in service
            await db.rollback()
    return {**result, "tab_renames": tab_renames}


@router.post("/{type_id}/rename")
async def rename_link_type(
    type_id: uuid.UUID, payload: LinkTypeRenameIn, db: DbSession,
    ctx: AuthContext = Depends(require_role(Role.MANAGER)),
) -> dict:
    """Correct a master's spelling everywhere (records, tasks, rates, tabs)."""
    result = await merge_svc.rename_type(db, ctx, type_id, payload.name)
    await audit_service.record(
        db, action=AuditAction.UPDATE, actor_user_id=ctx.user.id, workspace_id=ctx.workspace_id,
        entity_type="link_type", entity_id=type_id,
        summary=f"Renamed link type \"{result['renamed']['from']}\" to \"{result['renamed']['to']}\"",
        before={"name": result["renamed"]["from"]},
        after={"name": result["renamed"]["to"], "changed": result["changed"]},
    )
    await db.commit()
    tab_renames: list[dict] = []
    if payload.rename_tabs:
        tab_renames = await merge_svc.apply_sheet_tab_renames(
            db, ctx, result["renamed"]["from"], result["renamed"]["to"]
        )
        await db.commit()
    return {**result, "tab_renames": tab_renames}
