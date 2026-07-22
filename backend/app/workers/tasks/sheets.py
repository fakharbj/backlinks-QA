"""Google Sheets sync tasks (Phase 2).

``sync_main_sheet`` reads the global main sheet and fans out one
``sync_project_sheet`` per project — staggered so 1,000 sheets don't hit the
Sheets API all at once. Each project sync stages rows through the import
pipeline; new links stay "QA pending" until someone starts a check (or
``AUTO_QA_ON_IMPORT`` is enabled, which queues first crawls right away).
"""

from __future__ import annotations

import random
import uuid

from sqlalchemy.exc import OperationalError

from app.core.config import settings
from app.core.logging import get_logger
from app.db.session import session_scope
from app.services import sheet_sync_service
from app.workers.celery_app import celery_app
from app.workers.runtime import run_async

log = get_logger("worker.sheets")

# ── Global sheet-sync mutex ──────────────────────────────────────────────────
# Only ONE Sheets-heavy task (project sync / main-sheet discover / write-back)
# may talk to the Google API at a time, across every worker process. "Sync all
# sheets" queues everything at once; without this, several syncs run in
# parallel (worker concurrency) and together blow the per-user read quota.
# A busy task doesn't hold a worker slot — it requeues itself with a delay.
_SYNC_LOCK_KEY = "ls:sheets:synclock"
_SYNC_LOCK_TTL = 30 * 60  # safety expiry — a crashed holder frees the lock


def _lock_client():
    import redis

    return redis.Redis.from_url(
        str(settings.CELERY_BROKER_URL), socket_timeout=3, socket_connect_timeout=3
    )


def _acquire_sync_lock(owner: str) -> bool:
    try:
        return bool(_lock_client().set(_SYNC_LOCK_KEY, owner, nx=True, ex=_SYNC_LOCK_TTL))
    except Exception as exc:  # noqa: BLE001 — Redis down → don't deadlock syncs
        log.warning("sheets_lock_unavailable", error=repr(exc))
        return True


def _release_sync_lock(owner: str) -> None:
    try:
        client = _lock_client()
        # Compare-and-delete so a task whose lock expired can't free a newer holder.
        raw = client.get(_SYNC_LOCK_KEY)
        holder = raw.decode() if isinstance(raw, (bytes, bytearray)) else raw
        if holder == owner:
            client.delete(_SYNC_LOCK_KEY)
    except Exception:  # noqa: BLE001 — TTL will free it
        pass


def _run_serialized(task, owner: str, fn):
    """Run ``fn`` under the global sync lock; if another sheet task holds it,
    requeue this task in 20–40s (jitter avoids thundering-herd retries)."""
    if not _acquire_sync_lock(owner):
        raise task.retry(countdown=20 + random.randint(0, 20), max_retries=180)
    try:
        return fn()
    finally:
        _release_sync_lock(owner)


async def _sync_main_async(workspace_id: uuid.UUID) -> dict:
    async with session_scope() as s:
        discovery = await sheet_sync_service.discover_projects(s, workspace_id)

    # Main-sheet sync only DISCOVERS projects — it registers each project's name +
    # sheet link (and its tabs, for mapping) and applies the Status column, but
    # does NOT pull any links. The user sets the per-tab mapping (including which
    # tabs to ignore) first, then syncs a project's links explicitly
    # (POST /sheets/{id}/sync). This keeps reads far under the Sheets API quota
    # and enforces the "map first, then sync" flow.
    return {
        "discovered_projects": len(discovery["sheet_source_ids"]),
        "activated": discovery["activated"],
        "deactivated": discovery["deactivated"],
        "mode": "discover_only",
    }


async def _sync_project_async(sheet_source_id: uuid.UUID, parent_batch_id: str | None = None) -> dict:
    async with session_scope() as s:
        result = await sheet_sync_service.sync_project(
            s, sheet_source_id, parent_batch_id=parent_batch_id
        )

    # Manual-QA-by-default: only queue first crawls when explicitly configured.
    new_ids = [uuid.UUID(i) for i in result.get("new_ids", [])]
    if new_ids and settings.AUTO_QA_ON_IMPORT:
        from app.workers.dispatch import enqueue_backlinks

        enqueue_backlinks(new_ids)
    return {k: v for k, v in result.items() if k != "new_ids"}


@celery_app.task(
    name="tasks.sheets.sync_main_sheet", bind=True, acks_late=True, max_retries=3,
    autoretry_for=(OperationalError,), retry_backoff=True,
)
def sync_main_sheet(self, workspace_id: str) -> dict:
    return _run_serialized(
        self, f"main:{workspace_id}",
        lambda: run_async(_sync_main_async(uuid.UUID(workspace_id))),
    )


@celery_app.task(
    name="tasks.sheets.sync_project_sheet", bind=True, acks_late=True, max_retries=3,
    autoretry_for=(OperationalError,), retry_backoff=True,
)
def sync_project_sheet(self, sheet_source_id: str, parent_batch_id: str | None = None) -> dict:
    return _run_serialized(
        self, f"sync:{sheet_source_id}",
        lambda: run_async(_sync_project_async(uuid.UUID(sheet_source_id), parent_batch_id)),
    )


async def _writeback_async(sheet_source_id: uuid.UUID) -> dict:
    async with session_scope() as s:
        return await sheet_sync_service.writeback_project(s, sheet_source_id)


@celery_app.task(
    name="tasks.sheets.writeback_project_sheet", bind=True, acks_late=True, max_retries=2,
    autoretry_for=(OperationalError,), retry_backoff=True,
)
def writeback_project_sheet(self, sheet_source_id: str) -> dict:
    return _run_serialized(
        self, f"writeback:{sheet_source_id}",
        lambda: run_async(_writeback_async(uuid.UUID(sheet_source_id))),
    )


# ── Office-hours auto-sync (owner rule): sync every sheet automatically every
# N minutes, but ONLY inside the configured office hours AND on working days.
# All knobs live in the Setting KV "office_hours" (admin-editable in Settings). ──

OFFICE_DEFAULTS = {
    "start": "09:00", "end": "18:00", "tz": "Asia/Karachi",
    "auto_sync": False, "sync_interval_min": 30,
}


async def _office_cfg(db, workspace_id) -> dict:
    from sqlalchemy import select

    from app.models.settings import Setting

    row = (
        await db.execute(
            select(Setting).where(
                Setting.workspace_id == workspace_id, Setting.key == "office_hours"
            )
        )
    ).scalar_one_or_none()
    cfg = dict(OFFICE_DEFAULTS)
    if row is not None and isinstance(row.value, dict):
        cfg.update({k: v for k, v in row.value.items() if k in OFFICE_DEFAULTS})
    return cfg


async def _is_working_day(db, workspace_id, day) -> bool:
    from sqlalchemy import select

    from app.models.workforce import WorkingDay
    from app.services.workforce_service import _default_working

    override = (
        await db.execute(
            select(WorkingDay.is_working).where(
                WorkingDay.workspace_id == workspace_id, WorkingDay.day == day
            )
        )
    ).scalar_one_or_none()
    return override if override is not None else _default_working(day)


async def _heal_stale_parents(s, ws) -> int:
    """Close bulk parents that can never finish. A worker restart mid-run drops
    the queued child syncs, so the parent waits at status=running forever — the
    Batches list and the SheetsDesk progress card then show a phantom run. Any
    sheet_sync_all parent still open after 3 hours is closed as 'partial' with
    an honest note. Runs every tick, cheap (indexed status filter)."""
    from datetime import datetime, timedelta, timezone

    from sqlalchemy import select

    from app.models.batch import Batch
    from app.services import batch_service

    cutoff = datetime.now(timezone.utc) - timedelta(hours=3)
    stale = (
        await s.execute(
            select(Batch.id).where(
                Batch.workspace_id == ws,
                Batch.kind == "sheet_sync_all",
                Batch.status.in_(("pending", "running")),
                Batch.started_at < cutoff,
            )
        )
    ).scalars().all()
    for bid in stale:
        await batch_service.add_log(
            bid,
            "Run never finished (the worker restarted mid-run and the remaining "
            "project syncs were lost) — closed automatically as finished-with-problems.",
            level="warning",
        )
        await batch_service.finish(bid, status="partial", error="interrupted — worker restarted mid-run")
    return len(stale)


async def _auto_sync_tick_async() -> dict:
    from datetime import datetime
    from zoneinfo import ZoneInfo

    from sqlalchemy import select

    from app.models.sheets import SheetSource

    out: dict[str, str] = {}
    async with session_scope() as s:
        ws_ids = (
            await s.execute(select(SheetSource.workspace_id).distinct())
        ).scalars().all()
        for ws in ws_ids:
            # Self-heal BEFORE the office-hours gates so stuck runs clear even
            # on non-working days / disabled auto-sync.
            try:
                healed = await _heal_stale_parents(s, ws)
                if healed:
                    log.info("sheets_stale_parents_healed", workspace_id=str(ws), count=healed)
            except Exception as exc:  # noqa: BLE001 — healing must never block the tick
                log.warning("sheets_stale_parent_heal_failed", workspace_id=str(ws), error=repr(exc))
            cfg = await _office_cfg(s, ws)
            if not cfg.get("auto_sync"):
                out[str(ws)] = "disabled"
                continue
            try:
                tz = ZoneInfo(str(cfg.get("tz") or "UTC"))
            except Exception:  # noqa: BLE001 — bad tz string → UTC
                tz = ZoneInfo("UTC")
            now = datetime.now(tz)
            if not await _is_working_day(s, ws, now.date()):
                out[str(ws)] = "non_working_day"
                continue
            hhmm = now.strftime("%H:%M")
            if not (str(cfg["start"]) <= hhmm < str(cfg["end"])):
                out[str(ws)] = f"outside_hours({hhmm})"
                continue
            interval = max(10, min(int(cfg.get("sync_interval_min") or 30), 240))
            # One run per interval, cluster-wide: SET NX EX marks the slot.
            try:
                got = _lock_client().set(
                    f"ls:sheets:autosync:{ws}", now.isoformat(), nx=True, ex=interval * 60 - 30
                )
            except Exception:  # noqa: BLE001 — Redis down → skip this tick
                out[str(ws)] = "redis_unavailable"
                continue
            if not got:
                out[str(ws)] = "recently_ran"
                continue
            # Active projects ONLY (owner rule) — deactivated projects are
            # manual-sync only, never part of the automatic run.
            from app.models.enums import ProjectStatus
            from app.models.project import Project

            pairs = (
                await s.execute(
                    select(SheetSource.id, SheetSource.project_name)
                    .join(Project, Project.id == SheetSource.project_id)
                    .where(
                        SheetSource.workspace_id == ws,
                        Project.status == ProjectStatus.ACTIVE,
                    )
                )
            ).all()
            if not pairs:
                out[str(ws)] = "no_active_sheets"
                continue
            from app.services import batch_service

            parent_id = await batch_service.start(
                "sheet_sync_all", ws,
                label=f"Auto sync (office hours) — {len(pairs)} projects",
                total=len(pairs),
                meta={f"p:{sid}": {"name": name or "Project", "status": "pending"} for sid, name in pairs},
            )
            await batch_service.add_log(
                parent_id,
                f"Office-hours auto-sync: {len(pairs)} active project sheet(s) queued.",
            )
            for i, (sid, _name) in enumerate(pairs):
                sync_project_sheet.apply_async(
                    args=[str(sid)],
                    kwargs={"parent_batch_id": str(parent_id) if parent_id else None},
                    queue="sheets.sync", countdown=i * 10,
                )
            log.info("sheets_auto_sync_queued", workspace_id=str(ws), sheets=len(pairs))
            out[str(ws)] = f"queued:{len(pairs)}"
    return out


@celery_app.task(name="tasks.sheets.auto_sync_tick", bind=True, acks_late=True, max_retries=0)
def auto_sync_tick(self) -> dict:
    """Beat-driven every 5 min; the interval marker decides if a sync is due."""
    return run_async(_auto_sync_tick_async())
