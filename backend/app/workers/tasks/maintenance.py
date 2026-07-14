"""Scheduled maintenance tasks.

Celery beat calls these tasks to keep the operational loops moving: due crawls
are leased and queued, dashboard materialized views are refreshed, partitions are
rolled forward, and old fact/audit rows are pruned by retention policy.
"""

from __future__ import annotations

import uuid
from collections import defaultdict
from datetime import datetime, timedelta, timezone

from sqlalchemy import delete, func, select, update
from sqlalchemy.exc import OperationalError

from app.core.config import settings
from app.core.logging import get_logger
from app.db import init_db
from app.db.session import engine, session_scope
from app.models.audit import AuditLog
from app.models.backlink import BacklinkRecord
from app.models.crawl import CrawlJob
from app.models.enums import JobStatus, JobType, ProjectStatus
from app.models.project import Project
from app.workers.celery_app import celery_app
from app.workers.dispatch import enqueue_backlinks
from app.workers.runtime import run_async

log = get_logger("worker.maintenance")


async def _dispatch_due_rechecks_async(limit: int) -> dict:
    # Manual-first execution (Enterprise §7): scheduled auto-rechecks are OFF by
    # default — every QA run starts from an explicit user action. Flip
    # AUTO_SCHEDULED_RECHECKS=true to restore the always-on loop.
    from app.core.config import settings as _settings

    if not _settings.AUTO_SCHEDULED_RECHECKS:
        return {"queued": 0, "jobs": 0, "paused": "manual_mode"}

    now = datetime.now(timezone.utc)
    lease_until = now + timedelta(minutes=30)

    # ── API-aware scheduling (Enterprise §3): when the crawl proxy's configured
    # quota is exhausted, PAUSE the scheduled loop instead of dispatching work
    # that would fail (and burn what's left of every other API). Due links get
    # qa_wait_reason='waiting_api' so the UI explains the pause; a manual retry
    # (or the next day's quota) picks them back up.
    from app.services import api_usage_service

    if not await api_usage_service.available("iproyal"):
        async with session_scope() as s:
            res = await s.execute(
                update(BacklinkRecord)
                .where(
                    BacklinkRecord.next_check_at.is_not(None),
                    BacklinkRecord.next_check_at <= now,
                )
                .values(next_check_at=None, qa_wait_reason="waiting_api")
            )
            await s.commit()
        return {"queued": 0, "jobs": 0, "paused": "iproyal_quota", "parked": res.rowcount or 0}

    async with session_scope() as s:
        rows = (
            await s.execute(
                select(BacklinkRecord.id, BacklinkRecord.workspace_id)
                .join(Project, Project.id == BacklinkRecord.project_id)
                .where(
                    BacklinkRecord.next_check_at.is_not(None),
                    BacklinkRecord.next_check_at <= now,
                    Project.status == ProjectStatus.ACTIVE,
                )
                .order_by(BacklinkRecord.next_check_at.asc(), BacklinkRecord.id.asc())
                .limit(limit)
            )
        ).all()

        if not rows:
            return {"queued": 0, "jobs": 0}

        ids = [row.id for row in rows]
        by_workspace: dict[uuid.UUID, list[uuid.UUID]] = defaultdict(list)
        for row in rows:
            by_workspace[row.workspace_id].append(row.id)

        await s.execute(
            update(BacklinkRecord)
            .where(BacklinkRecord.id.in_(ids))
            .values(next_check_at=lease_until)
        )

        jobs: list[tuple[uuid.UUID, list[uuid.UUID]]] = []
        for workspace_id, workspace_ids in by_workspace.items():
            job = CrawlJob(
                workspace_id=workspace_id,
                project_id=None,
                job_type=JobType.SCHEDULED,
                status=JobStatus.PENDING,
                total=len(workspace_ids),
                params={"source": "due_rechecks", "lease_until": lease_until.isoformat()},
            )
            s.add(job)
            await s.flush()
            jobs.append((job.id, workspace_ids))

    queued = 0
    for job_id, job_ids in jobs:
        queued += enqueue_backlinks(job_ids, job_id=job_id, priority=False)
    return {"queued": queued, "jobs": len(jobs)}


async def _reconcile_stale_crawl_jobs_async(stale_minutes: int) -> dict:
    """Close out crawl/recheck jobs whose worker tasks were lost.

    A job (and its ops batch) is finalized by ``crawl._update_job`` ONLY when
    ``processed >= total``. If Celery tasks are lost (worker recycle/OOM,
    time-limit kill), that never happens, so the job — and the batch mirroring it —
    hang in 'running' forever (e.g. batch #B-7 stuck at 714/880). This sweep finds
    jobs with no progress (``crawl_jobs.updated_at``) for ``stale_minutes`` and
    finalizes them honestly: an incomplete job becomes PARTIAL showing its REAL
    progress; the un-checked links keep their recheck lease and are picked up on a
    later cycle. Fail-open per job so one bad row can't wedge the sweep.
    """
    from app.services import batch_service

    now = datetime.now(timezone.utc)
    cutoff = now - timedelta(minutes=stale_minutes)
    finalized: list[dict] = []

    async with session_scope() as s:
        # Anchor staleness on the last progress tick (updated_at bumps on every
        # _update_job); created_at is the fallback for a job that never ticked.
        last_progress = func.coalesce(CrawlJob.updated_at, CrawlJob.created_at)
        jobs = (
            await s.execute(
                select(CrawlJob)
                .where(
                    CrawlJob.status.in_([JobStatus.PENDING, JobStatus.RUNNING]),
                    last_progress < cutoff,
                )
                .order_by(CrawlJob.created_at.asc())
                .limit(500)
            )
        ).scalars().all()
        for job in jobs:
            incomplete = bool(job.total) and job.processed < job.total
            job.status = JobStatus.PARTIAL if (job.failed or incomplete) else JobStatus.COMPLETED
            job.finished_at = now
            missing = max(0, (job.total or 0) - (job.processed or 0))
            note = (
                f"auto-finalized: no progress for >= {stale_minutes} min "
                f"({job.processed}/{job.total} checked; {missing} link(s) had lost "
                "worker tasks — re-checked on the next cycle)"
            )
            job.error = ((job.error or "").strip() + " | " + note).strip(" |")
            finalized.append({
                "batch_id": str(job.batch_id) if job.batch_id else None,
                "total": int(job.total or 0),
                "processed": int(job.processed or 0),
                "succeeded": int(job.succeeded or 0),
                "failed": int(job.failed or 0),
                "incomplete": incomplete,
                "missing": missing,
            })

    # Mirror onto + close the linked ops batch (fail-open, separate sessions).
    for item in finalized:
        bid_s = item["batch_id"]
        if not bid_s:
            continue
        bid = uuid.UUID(bid_s)
        total = item["total"]
        await batch_service.update(
            bid,
            totals={
                "total": total,
                "done": min(item["processed"], total) if total else item["processed"],
                "ok": item["succeeded"],
                "failed": item["failed"],
            },
        )
        if item["incomplete"] or item["failed"]:
            await batch_service.add_log(
                bid,
                f"Auto-finalized: {item['missing']} link(s) weren't checked because "
                "their worker tasks were lost. Marked partial — they'll be re-checked "
                "on the next recheck cycle.",
                level="warn",
            )
            await batch_service.finish(bid, status="partial")
        else:
            await batch_service.finish(bid)

    if finalized:
        log.info("reconcile_stale_crawl_jobs", reconciled=len(finalized))
    return {"reconciled": len(finalized)}


async def _ensure_partitions_async(months_forward: int) -> dict:
    await init_db.ensure_future_partitions(engine, months_forward=months_forward)
    return {"months_forward": months_forward}


async def _retention_cleanup_async() -> dict:
    now = datetime.now(timezone.utc)
    history_cutoff = (now - timedelta(days=settings.RETENTION_HISTORY_DAYS)).date()
    audit_cutoff = now - timedelta(days=settings.RETENTION_AUDIT_DAYS)

    # Drop whole monthly partitions older than retention (efficient at scale) rather
    # than row DELETEs that would scan/bloat millions of rows.
    results = await init_db.drop_partitions_before(engine, "crawl_results", history_cutoff)
    history = await init_db.drop_partitions_before(engine, "backlink_history", history_cutoff)

    async with session_scope() as s:  # audit_log is not partitioned → DELETE
        audit = await s.execute(delete(AuditLog).where(AuditLog.created_at < audit_cutoff))
    return {
        "crawl_result_partitions_dropped": results,
        "history_partitions_dropped": history,
        "audit_deleted": audit.rowcount or 0,
    }


@celery_app.task(
    name="tasks.maintenance.dispatch_due_rechecks",
    bind=True,
    acks_late=True,
    max_retries=3,
    autoretry_for=(OperationalError,),
    retry_backoff=True,
)
def dispatch_due_rechecks(self, limit: int = 5000) -> dict:
    return run_async(_dispatch_due_rechecks_async(limit))


@celery_app.task(
    name="tasks.maintenance.reconcile_stale_crawl_jobs",
    bind=True,
    acks_late=True,
    max_retries=3,
    autoretry_for=(OperationalError,),
    retry_backoff=True,
)
def reconcile_stale_crawl_jobs(self, stale_minutes: int | None = None) -> dict:
    """Finalize crawl/recheck jobs (and their batches) stuck 'running' because
    some worker tasks were lost and never advanced the counters."""
    minutes = stale_minutes if stale_minutes is not None else settings.CRAWL_JOB_STALE_MINUTES
    return run_async(_reconcile_stale_crawl_jobs_async(minutes))


@celery_app.task(
    name="tasks.maintenance.ensure_partitions",
    bind=True,
    acks_late=True,
    max_retries=3,
    autoretry_for=(OperationalError,),
    retry_backoff=True,
)
def ensure_partitions(self, months_forward: int = 3) -> dict:
    return run_async(_ensure_partitions_async(months_forward))


@celery_app.task(
    name="tasks.maintenance.retention_cleanup",
    bind=True,
    acks_late=True,
    max_retries=3,
    autoretry_for=(OperationalError,),
    retry_backoff=True,
)
def retention_cleanup(self) -> dict:
    return run_async(_retention_cleanup_async())


async def _apply_week_templates_async() -> dict:
    from app.services import workforce_service

    async with session_scope() as s:
        return await workforce_service.auto_apply_templates(s)


@celery_app.task(
    name="tasks.maintenance.apply_week_templates",
    bind=True,
    acks_late=True,
    max_retries=3,
    autoretry_for=(OperationalError,),
    retry_backoff=True,
)
def apply_week_templates(self) -> dict:
    """Materialize NEXT week's plans from each workspace's weekly template
    (fill-gaps only — never overwrites manual planning)."""
    return run_async(_apply_week_templates_async())
