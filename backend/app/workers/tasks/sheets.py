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
        sheet_source_ids = await sheet_sync_service.discover_projects(s, workspace_id)

    # Main-sheet sync only DISCOVERS projects — it registers each project's name +
    # sheet link (and its tabs, for mapping) but does NOT pull any links. The user
    # sets the per-tab mapping (including which tabs to ignore) first, then syncs a
    # project's links explicitly (POST /sheets/{id}/sync). This keeps reads far
    # under the Sheets API quota and enforces the "map first, then sync" flow.
    return {"discovered_projects": len(sheet_source_ids), "mode": "discover_only"}


async def _sync_project_async(sheet_source_id: uuid.UUID) -> dict:
    async with session_scope() as s:
        result = await sheet_sync_service.sync_project(s, sheet_source_id)

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
def sync_project_sheet(self, sheet_source_id: str) -> dict:
    return _run_serialized(
        self, f"sync:{sheet_source_id}",
        lambda: run_async(_sync_project_async(uuid.UUID(sheet_source_id))),
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
