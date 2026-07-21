"""Batch registry helpers (Phase 9) — ALWAYS fail-open.

Runners (sheet sync, import worker, crawl dispatch, re-score, duplicate scan,
report worker) call these to record what's happening. Every helper opens its own
short session and swallows its own errors: a batch-bookkeeping failure must never
break the run it describes. ``start`` returns None on failure and every other
helper tolerates ``batch_id=None``, so call sites need no guards.
"""

from __future__ import annotations

import uuid
from datetime import datetime, timezone

from sqlalchemy import select

from app.core.logging import get_logger
from app.db.session import session_scope
from app.models.batch import Batch, BatchLog

log = get_logger("services.batch")


async def start(
    kind: str,
    workspace_id: uuid.UUID,
    *,
    project_id: uuid.UUID | None = None,
    label: str | None = None,
    started_by: uuid.UUID | None = None,
    total: int | None = None,
    meta: dict | None = None,
) -> uuid.UUID | None:
    try:
        async with session_scope() as s:
            row = Batch(
                workspace_id=workspace_id, project_id=project_id, kind=kind,
                status="running", label=(label or "")[:300] or None, started_by=started_by,
                totals={"total": total} if total is not None else {},
                counters={}, meta=meta or {},
            )
            s.add(row)
            await s.flush()
            return row.id
    except Exception as exc:  # noqa: BLE001 — fail-open by design
        log.warning("batch_start_failed", kind=kind, error=repr(exc))
        return None


async def update(
    batch_id: uuid.UUID | None,
    *,
    totals: dict | None = None,
    counters_inc: dict | None = None,
    label: str | None = None,
    meta: dict | None = None,
) -> None:
    """Merge progress totals / increment counters. ``totals`` keys overwrite;
    ``counters_inc`` keys add to the stored value."""
    if batch_id is None:
        return
    try:
        async with session_scope() as s:
            row = await s.get(Batch, batch_id)
            if row is None:
                return
            if totals:
                row.totals = {**(row.totals or {}), **totals}
            if counters_inc:
                merged = dict(row.counters or {})
                for k, v in counters_inc.items():
                    merged[k] = int(merged.get(k, 0)) + int(v)
                row.counters = merged
            if label:
                row.label = label[:300]
            if meta:
                row.meta = {**(row.meta or {}), **meta}
    except Exception as exc:  # noqa: BLE001
        log.warning("batch_update_failed", batch_id=str(batch_id), error=repr(exc))


async def get(batch_id: uuid.UUID | None) -> dict | None:
    """Read a batch's totals/counters/meta (fail-open, own session) — used by
    bulk-run children to decide when the parent batch is complete."""
    if batch_id is None:
        return None
    try:
        async with session_scope() as s:
            row = await s.get(Batch, batch_id)
            if row is None:
                return None
            return {
                "id": row.id, "status": row.status,
                "totals": dict(row.totals or {}),
                "counters": dict(row.counters or {}),
                "meta": dict(row.meta or {}),
            }
    except Exception as exc:  # noqa: BLE001
        log.warning("batch_get_failed", batch_id=str(batch_id), error=repr(exc))
        return None


async def add_log(
    batch_id: uuid.UUID | None,
    message: str,
    *,
    level: str = "info",
    row_ref: str | None = None,
    data: dict | None = None,
) -> None:
    if batch_id is None:
        return
    try:
        async with session_scope() as s:
            s.add(
                BatchLog(
                    batch_id=batch_id, level=level, message=message[:4000],
                    row_ref=(row_ref or "")[:120] or None, data=data or {},
                )
            )
    except Exception as exc:  # noqa: BLE001
        log.warning("batch_log_failed", batch_id=str(batch_id), error=repr(exc))


async def finish(
    batch_id: uuid.UUID | None,
    *,
    status: str | None = None,
    error: str | None = None,
) -> None:
    """Close a batch. Without an explicit status: failed if an error is given,
    partial when both ok and failed counts exist, else completed."""
    if batch_id is None:
        return
    info = None
    try:
        async with session_scope() as s:
            row = await s.get(Batch, batch_id)
            if row is None:
                return
            if status is None:
                t = row.totals or {}
                if error:
                    status = "failed"
                elif int(t.get("failed", 0) or 0) > 0 and int(t.get("ok", 0) or 0) > 0:
                    status = "partial"
                elif int(t.get("failed", 0) or 0) > 0 and not int(t.get("ok", 0) or 0):
                    status = "failed"
                else:
                    status = "completed"
            row.status = status
            row.error = (error or "")[:2000] or None
            row.finished_at = datetime.now(timezone.utc)
            info = {
                "kind": row.kind, "status": status, "seq": row.seq,
                "label": row.label, "workspace_id": row.workspace_id,
                "project_id": row.project_id, "started_by": row.started_by,
            }
    except Exception as exc:  # noqa: BLE001
        log.warning("batch_finish_failed", batch_id=str(batch_id), error=repr(exc))
    # ── User notifications (fail-open, own session): the ONE place every
    # long-running run ends, so "check finished / report ready / sync failed"
    # all hang off it. Preference-aware per recipient. ──
    if info is None:
        return
    try:
        from app.services import notification_service as ns

        kind, st = info["kind"], info["status"]
        name = info["label"] or f"#B-{info['seq']}"
        ref = {"tab": "batches", "batch_id": str(batch_id)}
        common = dict(project_id=info["project_id"], ref=ref)
        if kind in ("recheck", "crawl", "index_check") and info["started_by"]:
            word = "finished" if st == "completed" else f"finished — {st}"
            await ns.notify(info["workspace_id"], "qa_check_done",
                            f"Check {word}: {name}", user_ids=[info["started_by"]], **common)
        elif kind == "report" and info["started_by"]:
            await ns.notify(info["workspace_id"], "report_ready",
                            f"Report ready: {name}" if st == "completed" else f"Report {st}: {name}",
                            user_ids=[info["started_by"]], **common)
        elif kind in ("sheet_sync", "sheet_sync_all") and st in ("failed", "partial"):
            await ns.notify(info["workspace_id"], "sync_failed",
                            f"Sheet sync finished with problems: {name}",
                            body="Open the batch to see which rows or projects failed.",
                            user_ids=[info["started_by"]] if info["started_by"] else None,
                            to_admins=not info["started_by"], **common)
    except Exception as exc:  # noqa: BLE001
        log.warning("batch_finish_notify_failed", batch_id=str(batch_id), error=repr(exc))


async def list_batches(
    db,
    workspace_id: uuid.UUID,
    *,
    kind: str | None = None,
    status: str | None = None,
    project_id: uuid.UUID | None = None,
    limit: int = 100,
    offset: int = 0,
    parent_id: uuid.UUID | None = None,
    top_level: bool = False,
) -> list[Batch]:
    """``parent_id`` lists one bulk run's children; ``top_level`` hides children
    from the main list (a bulk run shows as ONE row — its children live inside
    the parent's details page). Both key off ``meta->>'parent_batch_id'``."""
    stmt = select(Batch).where(Batch.workspace_id == workspace_id)
    if kind:
        stmt = stmt.where(Batch.kind == kind)
    if status:
        stmt = stmt.where(Batch.status == status)
    if project_id:
        stmt = stmt.where(Batch.project_id == project_id)
    if parent_id is not None:
        stmt = stmt.where(Batch.meta["parent_batch_id"].astext == str(parent_id))
    elif top_level:
        stmt = stmt.where(Batch.meta["parent_batch_id"].astext.is_(None))
    stmt = (
        stmt.order_by(Batch.started_at.desc())
        .offset(max(0, offset))
        .limit(max(1, min(limit, 300)))
    )
    return list((await db.execute(stmt)).scalars().all())


async def get_logs(db, batch_id: uuid.UUID, *, limit: int = 500) -> list[BatchLog]:
    stmt = (
        select(BatchLog)
        .where(BatchLog.batch_id == batch_id)
        .order_by(BatchLog.created_at.asc())
        .limit(max(1, min(limit, 2000)))
    )
    return list((await db.execute(stmt)).scalars().all())
