"""Backlink conflict (duplicate group) endpoints (Phase 8, feature 9).

Read views over the fingerprint-detected duplicate groups, a workspace re-scan,
and a per-group resolution action. Listing is available to any authenticated
member (project-scoped); mutating actions require EDIT_BACKLINKS.
"""

from __future__ import annotations

import uuid

from fastapi import APIRouter, Depends

from app.core.deps import AuthContext, AuthCtx, DbSession, ReadSession, require
from app.core.rbac import Permission
from app.models.enums import AuditAction
from app.schemas.conflict import ConflictOut, ConflictResolve, ConflictSummaryOut
from app.services import audit_service, conflict_service

router = APIRouter(prefix="/conflicts", tags=["conflicts"])


@router.get("", response_model=list[ConflictOut])
async def list_conflicts(
    ctx: AuthCtx, db: ReadSession, status: str | None = None
) -> list[ConflictOut]:
    rows = await conflict_service.list_conflicts(db, ctx, status=status)
    return [ConflictOut(**row) for row in rows]


@router.get("/summary", response_model=ConflictSummaryOut)
async def conflict_summary(ctx: AuthCtx, db: ReadSession) -> ConflictSummaryOut:
    return ConflictSummaryOut(**await conflict_service.summary(db, ctx))


@router.post("/rebuild", response_model=ConflictSummaryOut)
async def rebuild_conflicts(
    db: DbSession, ctx: AuthContext = Depends(require(Permission.EDIT_BACKLINKS))
) -> ConflictSummaryOut:
    from app.services import batch_service

    batch_id = await batch_service.start(
        "duplicate_scan", ctx.workspace_id, label="Duplicate scan (all links)",
        started_by=ctx.user.id,
    )
    try:
        groups = await conflict_service.rebuild_workspace(db, ctx.workspace_id)
    except Exception as exc:  # noqa: BLE001 — close the batch, then surface the error
        await batch_service.finish(batch_id, status="failed", error=str(exc)[:500])
        raise
    await audit_service.record(
        db, action=AuditAction.UPDATE, actor_user_id=ctx.user.id,
        workspace_id=ctx.workspace_id, entity_type="conflict", entity_id=ctx.workspace_id,
        summary=f"Re-scanned duplicates ({groups} groups)",
    )
    await db.commit()
    await batch_service.update(batch_id, totals={"total": groups, "done": groups, "ok": groups})
    await batch_service.add_log(batch_id, f"Found {groups} duplicate group(s) across the workspace.")
    await batch_service.finish(batch_id)
    return ConflictSummaryOut(**await conflict_service.summary(db, ctx))


@router.post("/{conflict_id}/resolve", response_model=ConflictSummaryOut)
async def resolve_conflict(
    conflict_id: uuid.UUID, payload: ConflictResolve, db: DbSession,
    ctx: AuthContext = Depends(require(Permission.EDIT_BACKLINKS)),
) -> ConflictSummaryOut:
    conflict = await conflict_service.resolve(db, ctx, conflict_id, payload.resolution_status)
    await audit_service.record(
        db, action=AuditAction.UPDATE, actor_user_id=ctx.user.id,
        workspace_id=ctx.workspace_id, entity_type="conflict", entity_id=conflict.id,
        summary=f"Conflict {payload.resolution_status}",
    )
    await db.commit()
    return ConflictSummaryOut(**await conflict_service.summary(db, ctx))
