"""Index-check tasks (Phase 4).

``dispatch_index_checks`` selects the due source URLs and fans out one
``check_one_source`` per URL, staggered by INDEX_STAGGER_SECONDS so we don't
hammer Google. ``weekly_index_sweep`` is the beat-driven global version.
"""

from __future__ import annotations

import uuid

from sqlalchemy.exc import OperationalError

from app.core.config import settings
from app.core.logging import get_logger
from app.db.session import session_scope
from app.services import index_service
from app.workers.celery_app import celery_app
from app.workers.runtime import run_async

log = get_logger("worker.index")


async def _dispatch_async(
    workspace_id: uuid.UUID | None, project_id: uuid.UUID | None, force: bool
) -> dict:
    async with session_scope() as s:
        sources = await index_service.select_due_sources(
            s, workspace_id=workspace_id, project_id=project_id, force=force
        )
    stagger = max(0.0, settings.INDEX_STAGGER_SECONDS)
    for i, (ws, src_norm, url) in enumerate(sources):
        check_one_source.apply_async(
            args=[str(ws), src_norm, url, force],
            queue="index.check",
            countdown=stagger * i,
        )
    return {"dispatched": len(sources)}


async def _check_one_async(
    workspace_id: uuid.UUID, source_url_normalized: str, source_page_url: str, force: bool
) -> dict:
    async with session_scope() as s:
        return await index_service.check_source(
            s, workspace_id, source_url_normalized, source_page_url, force=force
        )


@celery_app.task(
    name="tasks.index.dispatch_index_checks", bind=True, acks_late=True, max_retries=3,
    autoretry_for=(OperationalError,), retry_backoff=True,
)
def dispatch_index_checks(
    self, workspace_id: str | None = None, project_id: str | None = None, force: bool = False
) -> dict:
    return run_async(
        _dispatch_async(
            uuid.UUID(workspace_id) if workspace_id else None,
            uuid.UUID(project_id) if project_id else None,
            force,
        )
    )


@celery_app.task(
    name="tasks.index.check_one_source", bind=True, acks_late=True, max_retries=2,
    autoretry_for=(OperationalError,), retry_backoff=True,
)
def check_one_source(
    self, workspace_id: str, source_url_normalized: str, source_page_url: str, force: bool = False
) -> dict:
    return run_async(
        _check_one_async(uuid.UUID(workspace_id), source_url_normalized, source_page_url, force)
    )


@celery_app.task(
    name="tasks.index.weekly_index_sweep", bind=True, acks_late=True, max_retries=1,
)
def weekly_index_sweep(self) -> dict:
    """Beat-driven: check every workspace's due source URLs (global)."""
    if not settings.INDEX_CHECK_ENABLED:
        return {"skipped": "disabled"}
    return run_async(_dispatch_async(None, None, False))
