"""Backlink conflict (duplicate group) endpoints (Phase 8, feature 9).

Read views over the fingerprint-detected duplicate groups, a workspace re-scan,
a per-group detail view, resolution + bulk actions, and a member CSV export.
Listing/detail are available to any authenticated member (project-scoped, with
cross-project groups exposed read-only to involved managers); mutating actions
require EDIT_BACKLINKS.
"""

from __future__ import annotations

import csv
import io
import uuid
from datetime import date

from fastapi import APIRouter, Depends
from starlette.responses import StreamingResponse

from app.core.deps import AuthContext, AuthCtx, DbSession, ReadSession, require
from app.core.rbac import Permission
from app.models.enums import AuditAction
from app.schemas.conflict import (
    ConflictBulk,
    ConflictDetailOut,
    ConflictKeepOne,
    ConflictListOut,
    ConflictOut,
    ConflictReassign,
    ConflictResolve,
    ConflictSummaryOut,
)
from app.services import audit_service, conflict_service

router = APIRouter(prefix="/conflicts", tags=["conflicts"])


@router.get("", response_model=ConflictListOut)
async def list_conflicts(
    ctx: AuthCtx,
    db: ReadSession,
    scope: str | None = None,
    status: str | None = None,
    project_id: str | None = None,
    user: str | None = None,
    detected_from: date | None = None,
    detected_to: date | None = None,
    created_from: date | None = None,
    created_to: date | None = None,
    min_members: int | None = None,
    min_similarity: int | None = None,
    max_similarity: int | None = None,
    target_domain: str | None = None,
    source_page: str | None = None,
    search: str | None = None,
    limit: int = 100,
    offset: int = 0,
) -> ConflictListOut:
    res = await conflict_service.list_conflicts(
        db, ctx, scope=scope, status=status, project_id=project_id, user=user,
        detected_from=detected_from, detected_to=detected_to,
        created_from=created_from, created_to=created_to, min_members=min_members,
        min_similarity=min_similarity, max_similarity=max_similarity,
        target_domain=target_domain, source_page=source_page, search=search,
        limit=limit, offset=offset,
    )
    return ConflictListOut(
        items=[ConflictOut(**row) for row in res["items"]],
        total=res["total"], limit=res["limit"], offset=res["offset"],
    )


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


@router.get("/{conflict_id}", response_model=ConflictDetailOut)
async def conflict_detail(
    conflict_id: uuid.UUID, ctx: AuthCtx, db: ReadSession
) -> ConflictDetailOut:
    return ConflictDetailOut(**await conflict_service.get_detail(db, ctx, conflict_id))


@router.get("/{conflict_id}/actions")
async def conflict_actions(
    conflict_id: uuid.UUID, ctx: AuthCtx, db: ReadSession
) -> list[dict]:
    # Workspace-scoped; readable even after the group collapsed (audit outlives it).
    return await conflict_service.list_actions(db, ctx, conflict_id)


@router.get("/{conflict_id}/members")
async def export_conflict_members(
    conflict_id: uuid.UUID, ctx: AuthCtx, db: ReadSession
) -> StreamingResponse:
    headers, rows = await conflict_service.export_members(db, ctx, conflict_id)
    buf = io.StringIO()
    w = csv.writer(buf)
    w.writerow(headers)
    w.writerows(rows)
    data = buf.getvalue()
    safe = f"conflict-{conflict_id}".encode("ascii", "ignore").decode("ascii") or "conflict"
    return StreamingResponse(
        iter([data]), media_type="text/csv; charset=utf-8",
        headers={"Content-Disposition": f'attachment; filename="{safe}.csv"'},
    )


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


@router.post("/{conflict_id}/keep-one")
async def keep_one(
    conflict_id: uuid.UUID, payload: ConflictKeepOne, db: DbSession,
    ctx: AuthContext = Depends(require(Permission.EDIT_BACKLINKS)),
) -> dict:
    result = await conflict_service.keep_one(db, ctx, conflict_id, payload.keep_backlink_id)
    await audit_service.record(
        db, action=AuditAction.DELETE, actor_user_id=ctx.user.id,
        workspace_id=ctx.workspace_id, entity_type="conflict", entity_id=conflict_id,
        summary=f"Kept one link, removed {result['deleted_count']} duplicate(s)",
    )
    await db.commit()
    return result


@router.post("/{conflict_id}/delete-extras")
async def delete_extras(
    conflict_id: uuid.UUID, payload: ConflictKeepOne, db: DbSession,
    ctx: AuthContext = Depends(require(Permission.EDIT_BACKLINKS)),
) -> dict:
    # Alias of keep-one.
    result = await conflict_service.keep_one(db, ctx, conflict_id, payload.keep_backlink_id)
    await audit_service.record(
        db, action=AuditAction.DELETE, actor_user_id=ctx.user.id,
        workspace_id=ctx.workspace_id, entity_type="conflict", entity_id=conflict_id,
        summary=f"Deleted {result['deleted_count']} extra duplicate(s)",
    )
    await db.commit()
    return result


@router.post("/{conflict_id}/reassign")
async def reassign_conflict(
    conflict_id: uuid.UUID, payload: ConflictReassign, db: DbSession,
    ctx: AuthContext = Depends(require(Permission.EDIT_BACKLINKS)),
) -> dict:
    result = await conflict_service.reassign(db, ctx, conflict_id, payload.to_user_label)
    await audit_service.record(
        db, action=AuditAction.UPDATE, actor_user_id=ctx.user.id,
        workspace_id=ctx.workspace_id, entity_type="conflict", entity_id=conflict_id,
        summary=f"Reassigned {result['changed']} link(s) to {result['to_user_label']}",
    )
    await db.commit()
    return result


@router.post("/bulk")
async def bulk_conflicts(
    payload: ConflictBulk, db: DbSession,
    ctx: AuthContext = Depends(require(Permission.EDIT_BACKLINKS)),
) -> dict:
    result = await conflict_service.bulk_status(db, ctx, payload.conflict_ids, payload.action)
    await audit_service.record(
        db, action=AuditAction.UPDATE, actor_user_id=ctx.user.id,
        workspace_id=ctx.workspace_id, entity_type="conflict", entity_id=ctx.workspace_id,
        summary=f"Bulk {payload.action}: {result['updated']} group(s)",
    )
    await db.commit()
    return result
