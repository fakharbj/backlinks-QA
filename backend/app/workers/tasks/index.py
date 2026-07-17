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


# ── Time-based index TRACKING (owner rule): when a link's age crosses a
# checkpoint (e.g. 1 / 7 / 30 days after it was built), re-check its indexing —
# so "how fast do our links index" is measurable per cohort. Config lives in
# the Setting KV "index_tracking" (admin-editable in Settings); serper quota is
# respected (skips the tick when the daily limit is exhausted). ──

TRACKING_DEFAULTS = {"enabled": False, "checkpoints": [1, 7, 30], "daily_cap": 300}


async def _tracking_tick_async() -> dict:
    from datetime import date, timedelta

    from sqlalchemy import Date, cast, func, select

    from app.models.backlink import BacklinkRecord
    from app.models.settings import Setting
    from app.services import api_usage_service

    out: dict[str, str] = {}
    if not settings.INDEX_CHECK_ENABLED:
        return {"skipped": "index checks disabled"}
    if not await api_usage_service.available("serper"):
        return {"skipped": "serper quota exhausted — resumes after reset"}
    today = date.today()
    async with session_scope() as s:
        ws_rows = (
            await s.execute(
                select(Setting).where(Setting.key == "index_tracking")
            )
        ).scalars().all()
        for row in ws_rows:
            cfg = dict(TRACKING_DEFAULTS)
            if isinstance(row.value, dict):
                cfg.update({k: v for k, v in row.value.items() if k in TRACKING_DEFAULTS})
            if not cfg.get("enabled"):
                out[str(row.workspace_id)] = "disabled"
                continue
            checkpoints = sorted({int(c) for c in (cfg.get("checkpoints") or []) if 1 <= int(c) <= 365})
            if not checkpoints:
                out[str(row.workspace_id)] = "no checkpoints"
                continue
            cap = max(10, min(int(cfg.get("daily_cap") or 300), 2000))
            link_day = func.coalesce(
                BacklinkRecord.placement_date,
                cast(func.timezone("UTC", BacklinkRecord.created_at), Date),
            )
            target_days = [today - timedelta(days=c) for c in checkpoints]
            sources = (
                await s.execute(
                    select(
                        BacklinkRecord.source_url_normalized,
                        func.min(BacklinkRecord.source_page_url),
                    )
                    .where(
                        BacklinkRecord.workspace_id == row.workspace_id,
                        link_day.in_(target_days),
                        # Not checked today already (one tracking check per day max).
                        func.coalesce(
                            cast(func.timezone("UTC", BacklinkRecord.index_checked_at), Date),
                            date(1970, 1, 1),
                        ) < today,
                    )
                    .group_by(BacklinkRecord.source_url_normalized)
                    .limit(cap)
                )
            ).all()
            stagger = max(0.0, settings.INDEX_STAGGER_SECONDS)
            for i, (src_norm, url) in enumerate(sources):
                check_one_source.apply_async(
                    args=[str(row.workspace_id), src_norm, url, True],
                    queue="index.check",
                    countdown=stagger * i,
                )
            log.info(
                "index_tracking_queued", workspace_id=str(row.workspace_id),
                sources=len(sources), checkpoints=checkpoints,
            )
            out[str(row.workspace_id)] = f"queued:{len(sources)}"
    return out


@celery_app.task(name="tasks.index.tracking_tick", bind=True, acks_late=True, max_retries=0)
def tracking_tick(self) -> dict:
    """Beat-driven daily: re-check links whose age crossed a tracking checkpoint."""
    return run_async(_tracking_tick_async())
