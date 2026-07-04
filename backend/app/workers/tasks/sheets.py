"""Google Sheets sync tasks (Phase 2).

``sync_main_sheet`` reads the global main sheet and fans out one
``sync_project_sheet`` per project — staggered so 1,000 sheets don't hit the
Sheets API all at once. Each project sync stages rows through the import
pipeline; new links stay "QA pending" until someone starts a check (or
``AUTO_QA_ON_IMPORT`` is enabled, which queues first crawls right away).
"""

from __future__ import annotations

import uuid

from sqlalchemy.exc import OperationalError

from app.core.config import settings
from app.core.logging import get_logger
from app.db.session import session_scope
from app.services import sheet_sync_service
from app.workers.celery_app import celery_app
from app.workers.runtime import run_async

log = get_logger("worker.sheets")


async def _sync_main_async(workspace_id: uuid.UUID) -> dict:
    async with session_scope() as s:
        sheet_source_ids = await sheet_sync_service.discover_projects(s, workspace_id)

    stagger = max(0.0, settings.GOOGLE_SYNC_STAGGER_SECONDS)
    for index, sid in enumerate(sheet_source_ids):
        sync_project_sheet.apply_async(
            args=[str(sid)], queue="sheets.sync", countdown=stagger * index
        )
    return {"projects": len(sheet_source_ids)}


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
    return run_async(_sync_main_async(uuid.UUID(workspace_id)))


@celery_app.task(
    name="tasks.sheets.sync_project_sheet", bind=True, acks_late=True, max_retries=3,
    autoretry_for=(OperationalError,), retry_backoff=True,
)
def sync_project_sheet(self, sheet_source_id: str) -> dict:
    return run_async(_sync_project_async(uuid.UUID(sheet_source_id)))


async def _writeback_async(sheet_source_id: uuid.UUID) -> dict:
    async with session_scope() as s:
        return await sheet_sync_service.writeback_project(s, sheet_source_id)


@celery_app.task(
    name="tasks.sheets.writeback_project_sheet", bind=True, acks_late=True, max_retries=2,
    autoretry_for=(OperationalError,), retry_backoff=True,
)
def writeback_project_sheet(self, sheet_source_id: str) -> dict:
    return run_async(_writeback_async(uuid.UUID(sheet_source_id)))
