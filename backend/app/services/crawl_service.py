"""Crawl job creation + recheck target selection.

DB-only: it figures out *which* backlinks to crawl and records a ``CrawlJob``. The
router commits, then hands the id list to the dispatcher (``app.workers.dispatch``)
which shards by domain and enqueues batch tasks. Keeping this layer free of Celery
imports avoids a service↔worker import cycle.
"""

from __future__ import annotations

import uuid
from datetime import datetime, timedelta, timezone

from sqlalchemy import Select, func, or_, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.deps import AuthContext
from app.core.errors import NotFoundError
from app.models.backlink import BacklinkRecord
from app.models.crawl import CrawlJob
from app.models.enums import JobStatus, JobType, OverallStatus
from app.schemas.backlink import RecheckRequest


def _scope(stmt: Select, ctx: AuthContext) -> Select:
    stmt = stmt.where(BacklinkRecord.workspace_id == ctx.workspace_id)
    if ctx.allowed_project_ids is not None:
        stmt = stmt.where(BacklinkRecord.project_id.in_(ctx.allowed_project_ids or {uuid.uuid4()}))
    return stmt


async def select_recheck_ids(
    db: AsyncSession, ctx: AuthContext, req: RecheckRequest, *, limit: int = 100_000
) -> list[uuid.UUID]:
    stmt = _scope(select(BacklinkRecord.id), ctx)
    if req.backlink_ids:
        stmt = stmt.where(BacklinkRecord.id.in_(req.backlink_ids))
    if req.project_id:
        stmt = stmt.where(BacklinkRecord.project_id == req.project_id)
    if req.vendor_id:
        stmt = stmt.where(BacklinkRecord.vendor_id == req.vendor_id)
    if req.campaign_id:
        stmt = stmt.where(BacklinkRecord.campaign_id == req.campaign_id)
    effective = func.coalesce(BacklinkRecord.override_status, BacklinkRecord.status)
    if req.only_failed:
        stmt = stmt.where(effective == OverallStatus.FAIL)
    if req.only_warnings:
        stmt = stmt.where(effective == OverallStatus.WARNING)
    if req.older_than_days:
        cutoff = datetime.now(timezone.utc) - timedelta(days=req.older_than_days)
        stmt = stmt.where(
            or_(
                BacklinkRecord.last_checked_at.is_(None),
                BacklinkRecord.last_checked_at <= cutoff,
            )
        )
    stmt = stmt.limit(limit)
    return list((await db.execute(stmt)).scalars().all())


async def create_job(
    db: AsyncSession,
    ctx: AuthContext,
    *,
    ids: list[uuid.UUID],
    project_id: uuid.UUID | None,
    job_type: JobType,
) -> CrawlJob:
    job = CrawlJob(
        workspace_id=ctx.workspace_id,
        project_id=project_id,
        job_type=job_type,
        status=JobStatus.PENDING,
        triggered_by=ctx.user.id,
        total=len(ids),
    )
    db.add(job)
    await db.flush()
    return job


async def get_job(db: AsyncSession, ctx: AuthContext, job_id: uuid.UUID) -> CrawlJob:
    job = await db.get(CrawlJob, job_id)
    if job is None or job.workspace_id != ctx.workspace_id:
        raise NotFoundError("Crawl job not found")
    return job


async def due_backlinks(db: AsyncSession, *, limit: int = 5000) -> list[uuid.UUID]:
    """Scheduler helper: backlinks whose ``next_check_at`` has passed (active projects)."""
    from app.models.project import Project

    now = datetime.now(timezone.utc)
    stmt = (
        select(BacklinkRecord.id)
        .join(Project, Project.id == BacklinkRecord.project_id)
        .where(
            BacklinkRecord.next_check_at.is_not(None),
            BacklinkRecord.next_check_at <= now,
            Project.status == "active",
        )
        .order_by(BacklinkRecord.next_check_at.asc())
        .limit(limit)
    )
    return list((await db.execute(stmt)).scalars().all())
