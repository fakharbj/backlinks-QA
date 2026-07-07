"""Batch history endpoints (Phase 9) — the operations layer over every run.

0029 adds the review layer: batches of kind ``link_review``/``domain_import``
carry ``batch_items`` (staged links/domains) with their own item endpoints —
list/filter, run checks, approve into production, reject. See
``services.batch_review_service`` for the semantics.
"""

from __future__ import annotations

import uuid

from fastapi import APIRouter, Depends, Query
from starlette.responses import StreamingResponse
from pydantic import BaseModel, Field
from sqlalchemy import func, select

from app.core.deps import AuthContext, AuthCtx, DbSession, ReadSession, require
from app.core.errors import NotFoundError
from app.core.rbac import Permission
from app.models.batch import Batch, BatchItem, BatchLog
from app.models.enums import AuditAction
from app.services import audit_service, batch_review_service, batch_service

router = APIRouter(prefix="/batches", tags=["batches"])


class BatchOut(BaseModel):
    id: uuid.UUID
    seq: int
    kind: str
    status: str
    label: str | None
    project_id: uuid.UUID | None
    started_by: uuid.UUID | None
    totals: dict
    counters: dict
    meta: dict
    error: str | None
    started_at: str
    finished_at: str | None
    # Review batches only: items still awaiting a decision (pending/checking/
    # checked/failed). None for plain operation batches.
    review_pending: int | None = None


class BatchLogOut(BaseModel):
    level: str
    message: str
    row_ref: str | None
    data: dict
    created_at: str


class ItemSelection(BaseModel):
    """Target items either explicitly (``item_ids``) or by the same filters the
    items list uses (state/presence/search + DA/PA/Spam/AS thresholds) —
    'approve/export everything I filtered'."""

    item_ids: list[uuid.UUID] | None = Field(default=None, max_length=20000)
    state: str | None = None      # comma list: pending,checked,failed
    presence: str | None = None   # comma list: new,existing,duplicate
    q: str | None = Field(default=None, max_length=300)
    da_min: int | None = None
    da_max: int | None = None
    pa_min: int | None = None
    pa_max: int | None = None
    spam_min: int | None = None
    spam_max: int | None = None
    as_min: int | None = None
    as_max: int | None = None

    def thresholds(self) -> dict:
        return {k: getattr(self, k) for k in
                ("da_min", "da_max", "pa_min", "pa_max", "spam_min", "spam_max", "as_min", "as_max")}


class CheckRequest(ItemSelection):
    providers: str | None = None  # domain batches: "moz", "semrush" or "moz,semrush"


def _out(b: Batch, review_pending: int | None = None) -> BatchOut:
    return BatchOut(
        id=b.id, seq=b.seq, kind=b.kind, status=b.status, label=b.label,
        project_id=b.project_id, started_by=b.started_by, totals=b.totals or {},
        counters=b.counters or {}, meta=b.meta or {}, error=b.error,
        started_at=b.started_at.isoformat(),
        finished_at=b.finished_at.isoformat() if b.finished_at else None,
        review_pending=review_pending,
    )


async def _pending_by_batch(db, batch_ids: list[uuid.UUID]) -> dict[uuid.UUID, int]:
    if not batch_ids:
        return {}
    rows = await db.execute(
        select(BatchItem.batch_id, func.count())
        .where(
            BatchItem.batch_id.in_(batch_ids),
            BatchItem.state.in_(batch_review_service._OPEN_STATES),
        )
        .group_by(BatchItem.batch_id)
    )
    return {bid: n for bid, n in rows.all()}


@router.get("", response_model=list[BatchOut])
async def list_batches(
    ctx: AuthCtx,
    db: ReadSession,
    kind: str | None = Query(None),
    status: str | None = Query(None),
    project_id: uuid.UUID | None = Query(None),
    limit: int = Query(100),
) -> list[BatchOut]:
    if project_id is not None:
        ctx.assert_project(project_id)
    rows = await batch_service.list_batches(
        db, ctx.workspace_id, kind=kind, status=status, project_id=project_id, limit=limit
    )
    review_ids = [b.id for b in rows if b.kind in batch_review_service.REVIEW_KINDS]
    pending = await _pending_by_batch(db, review_ids)
    return [
        _out(b, pending.get(b.id, 0) if b.kind in batch_review_service.REVIEW_KINDS else None)
        for b in rows
    ]


@router.get("/{batch_id}", response_model=BatchOut)
async def get_batch(batch_id: uuid.UUID, ctx: AuthCtx, db: ReadSession) -> BatchOut:
    b = await db.get(Batch, batch_id)
    if b is None or b.workspace_id != ctx.workspace_id:
        raise NotFoundError("Batch not found")
    pending = None
    if b.kind in batch_review_service.REVIEW_KINDS:
        pending = (await _pending_by_batch(db, [b.id])).get(b.id, 0)
    return _out(b, pending)


@router.get("/{batch_id}/rollback-preview")
async def rollback_preview(batch_id: uuid.UUID, ctx: AuthCtx, db: ReadSession) -> dict:
    """What a *revert* delete would remove — drives the typed-name confirm dialog
    (created links, catalog domains) vs what stays (refreshed links, in-use domains)."""
    from app.services import batch_rollback_service

    return await batch_rollback_service.preview(db, ctx, batch_id)


@router.delete("/{batch_id}")
async def delete_batch(
    batch_id: uuid.UUID, db: DbSession,
    revert: bool = Query(False),
    ctx: AuthContext = Depends(require(Permission.MANAGE_WORKSPACE)),
) -> dict:
    """Delete one run. Default (``revert=false``) is admin housekeeping — logs +
    staged items go with it, approved data stays. ``revert=true`` also removes the
    rows this batch CREATED (links it inserted, catalog-only imported domains),
    leaving refreshed/in-use rows and all crawl history intact. Audited either way."""
    from app.services import batch_rollback_service

    return await batch_rollback_service.delete_batch(db, ctx, batch_id, revert=revert)


@router.get("/{batch_id}/logs", response_model=list[BatchLogOut])
async def get_batch_logs(batch_id: uuid.UUID, ctx: AuthCtx, db: ReadSession) -> list[BatchLogOut]:
    b = await db.get(Batch, batch_id)
    if b is None or b.workspace_id != ctx.workspace_id:
        raise NotFoundError("Batch not found")
    logs = await batch_service.get_logs(db, batch_id)
    if not logs:
        # Never show an empty log panel: synthesize a line from the batch itself.
        kind = batch_review_service.BATCH_KIND_LABEL.get(b.kind, b.kind) if hasattr(
            batch_review_service, "BATCH_KIND_LABEL"
        ) else b.kind
        step = (b.meta or {}).get("current_step")
        msg = f"{kind} — status: {b.status}."
        if step:
            msg += f" {step}"
        return [
            BatchLogOut(
                level="info", message=msg, row_ref=None, data={},
                created_at=(b.started_at or b.created_at).isoformat(),
            )
        ]
    return [
        BatchLogOut(
            level=r.level, message=r.message, row_ref=r.row_ref, data=r.data or {},
            created_at=r.created_at.isoformat(),
        )
        for r in logs
    ]


# ── Review items (0029) ──────────────────────────────────────────────────────


@router.get("/{batch_id}/items")
async def list_batch_items(
    batch_id: uuid.UUID,
    ctx: AuthCtx,
    db: ReadSession,
    state: str | None = Query(None, max_length=120),
    presence: str | None = Query(None, max_length=120),
    q: str | None = Query(None, max_length=300),
    da_min: int | None = Query(None),
    da_max: int | None = Query(None),
    pa_min: int | None = Query(None),
    pa_max: int | None = Query(None),
    spam_min: int | None = Query(None),
    spam_max: int | None = Query(None),
    as_min: int | None = Query(None),
    as_max: int | None = Query(None),
    limit: int = Query(200, ge=1, le=500),
    offset: int = Query(0, ge=0),
) -> dict:
    """The staged rows of a review batch with live counts — filters mirror the UI
    chips (comma lists) + substring search + DA/PA/Spam/AS thresholds."""
    thresholds = {"da_min": da_min, "da_max": da_max, "pa_min": pa_min, "pa_max": pa_max,
                  "spam_min": spam_min, "spam_max": spam_max, "as_min": as_min, "as_max": as_max}
    return await batch_review_service.list_items(
        db, ctx, batch_id, state=state, presence=presence, q=q, thresholds=thresholds,
        limit=limit, offset=offset,
    )


@router.get("/{batch_id}/items/export")
async def export_batch_items(
    batch_id: uuid.UUID,
    ctx: AuthCtx,
    db: ReadSession,
    format: str = Query("csv", pattern="^(csv|xlsx)$"),
    state: str | None = Query(None, max_length=120),
    presence: str | None = Query(None, max_length=120),
    q: str | None = Query(None, max_length=300),
    da_min: int | None = Query(None),
    da_max: int | None = Query(None),
    pa_min: int | None = Query(None),
    pa_max: int | None = Query(None),
    spam_min: int | None = Query(None),
    spam_max: int | None = Query(None),
    as_min: int | None = Query(None),
    as_max: int | None = Query(None),
) -> StreamingResponse:
    """Export the FULL filtered set of a batch's staged rows (honoring DA/PA/Spam/AS
    thresholds) as CSV or XLSX — pull the best candidates straight from the queue."""
    from app.services import source_domain_service

    thresholds = {"da_min": da_min, "da_max": da_max, "pa_min": pa_min, "pa_max": pa_max,
                  "spam_min": spam_min, "spam_max": spam_max, "as_min": as_min, "as_max": as_max}
    headers, rows = await batch_review_service.export_items(
        db, ctx, batch_id, state=state, presence=presence, q=q, thresholds=thresholds
    )
    if format == "xlsx":
        data = source_domain_service.build_xlsx(headers, rows, title="Batch items")
        media, ext = ("application/vnd.openxmlformats-officedocument.spreadsheetml.sheet", "xlsx")
    else:
        data = source_domain_service.build_csv(headers, rows)
        media, ext = ("text/csv; charset=utf-8", "csv")
    return StreamingResponse(
        iter([data]), media_type=media,
        headers={"Content-Disposition": f'attachment; filename="batch-items.{ext}"'},
    )


@router.post("/{batch_id}/items/check")
async def check_batch_items(
    batch_id: uuid.UUID,
    payload: CheckRequest,
    db: DbSession,
    ctx: AuthContext = Depends(require(Permission.RUN_CRAWLS)),
) -> dict:
    """Run the batch's check on selected/filtered items.

    Links: full isolated QA (real crawl on the worker; verdicts stay in the
    batch). Domains: DA/PA/Spam/AS/age fetched inline, capped per call.
    """
    b = await batch_review_service.load_batch(db, ctx, batch_id, review_only=True)
    if b.kind == "link_review":
        ids = await batch_review_service.begin_link_check(
            db, ctx, batch_id, item_ids=payload.item_ids,
            state=payload.state, presence=payload.presence, q=payload.q,
        )  # (link QA has no metric thresholds)
        # Chunk size honors this workspace's QA execution settings.
        from app.services import qa_settings_service

        qa_cfg = await qa_settings_service.get_effective(db, ctx.workspace_id)
        await db.commit()
        if ids:
            from app.workers.dispatch import enqueue_staged_check

            enqueue_staged_check(batch_id, ids, chunk_size=qa_cfg.get("chunk_size"))
        return {"queued": len(ids), "mode": "qa"}
    providers = {
        p.strip() for p in (payload.providers or "").split(",") if p.strip() in ("moz", "semrush")
    } or None
    result = await batch_review_service.check_domain_items(
        db, ctx, batch_id, item_ids=payload.item_ids, providers=providers,
        state=payload.state, presence=payload.presence, q=payload.q,
        thresholds=payload.thresholds(),
    )
    await db.commit()
    return {**result, "mode": "metrics"}


@router.post("/{batch_id}/items/approve")
async def approve_batch_items(
    batch_id: uuid.UUID,
    payload: ItemSelection,
    db: DbSession,
    ctx: AuthContext = Depends(require(Permission.IMPORT_BACKLINKS)),
) -> dict:
    """Approve staged items into production (links → normal import pipeline,
    domains → source-domain catalog). Only pending/checked items qualify."""
    result = await batch_review_service.approve_items(
        db, ctx, batch_id, item_ids=payload.item_ids,
        state=payload.state, presence=payload.presence, q=payload.q,
        thresholds=payload.thresholds(),
    )
    await audit_service.record(
        db, action=AuditAction.IMPORT, actor_user_id=ctx.user.id, workspace_id=ctx.workspace_id,
        entity_type="batch", entity_id=batch_id,
        summary=f"Approved {result.get('approved', 0)} staged items",
    )
    await db.commit()
    return result


@router.post("/{batch_id}/items/reject")
async def reject_batch_items(
    batch_id: uuid.UUID,
    payload: ItemSelection,
    db: DbSession,
    ctx: AuthContext = Depends(require(Permission.IMPORT_BACKLINKS)),
) -> dict:
    """Reject staged items — they stay visible in the batch for the audit
    trail but can never be imported."""
    result = await batch_review_service.reject_items(
        db, ctx, batch_id, item_ids=payload.item_ids,
        state=payload.state, presence=payload.presence, q=payload.q,
        thresholds=payload.thresholds(),
    )
    await db.commit()
    return result
