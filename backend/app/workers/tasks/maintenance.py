"""Scheduled maintenance tasks.

Celery beat calls these tasks to keep the operational loops moving: due crawls
are leased and queued, dashboard materialized views are refreshed, partitions are
rolled forward, and old fact/audit rows are pruned by retention policy.
"""

from __future__ import annotations

import uuid
from collections import defaultdict
from datetime import datetime, timedelta, timezone

from sqlalchemy import delete, select, update
from sqlalchemy.exc import OperationalError

from app.core.config import settings
from app.core.logging import get_logger
from app.db import init_db
from app.db.session import engine, session_scope
from app.models.audit import AuditLog
from app.models.backlink import BacklinkRecord
from app.models.crawl import BacklinkHistory, CrawlJob, CrawlResult
from app.models.enums import JobStatus, JobType, ProjectStatus
from app.models.project import Project
from app.workers.celery_app import celery_app
from app.workers.dispatch import enqueue_backlinks
from app.workers.runtime import run_async

log = get_logger("worker.maintenance")


async def _dispatch_due_rechecks_async(limit: int) -> dict:
    now = datetime.now(timezone.utc)
    lease_until = now + timedelta(minutes=30)

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


async def _ensure_partitions_async(months_forward: int) -> dict:
    await init_db.ensure_future_partitions(engine, months_forward=months_forward)
    return {"months_forward": months_forward}


async def _retention_cleanup_async() -> dict:
    now = datetime.now(timezone.utc)
    history_cutoff = now - timedelta(days=settings.RETENTION_HISTORY_DAYS)
    audit_cutoff = now - timedelta(days=settings.RETENTION_AUDIT_DAYS)
    result_cutoff = history_cutoff

    async with session_scope() as s:
        history = await s.execute(delete(BacklinkHistory).where(BacklinkHistory.created_at < history_cutoff))
        results = await s.execute(delete(CrawlResult).where(CrawlResult.crawled_at < result_cutoff))
        audit = await s.execute(delete(AuditLog).where(AuditLog.created_at < audit_cutoff))
    return {
        "history_deleted": history.rowcount or 0,
        "crawl_results_deleted": results.rowcount or 0,
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
