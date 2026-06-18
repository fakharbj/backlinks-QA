"""Report record lifecycle. Generation runs in the reports worker pool."""

from __future__ import annotations

import uuid

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.deps import AuthContext
from app.core.errors import NotFoundError, PermissionDeniedError
from app.models.report import Report
from app.schemas.report import ReportCreate


async def create_report(db: AsyncSession, ctx: AuthContext, payload: ReportCreate) -> Report:
    if payload.project_id is not None:
        ctx.assert_project(payload.project_id)
    elif ctx.allowed_project_ids is not None:
        raise PermissionDeniedError("Project-scoped users must select a project for reports")

    report = Report(
        workspace_id=ctx.workspace_id,
        project_id=payload.project_id,
        created_by=ctx.user.id,
        report_type=payload.report_type,
        format=payload.format,
        title=payload.title,
        filters=payload.filters,
    )
    db.add(report)
    await db.flush()
    return report


async def list_reports(db: AsyncSession, ctx: AuthContext) -> list[Report]:
    stmt = select(Report).where(Report.workspace_id == ctx.workspace_id)
    if ctx.allowed_project_ids is not None:
        stmt = stmt.where(Report.project_id.in_(ctx.allowed_project_ids or {uuid.uuid4()}))
    stmt = stmt.order_by(Report.created_at.desc()).limit(100)
    return list((await db.execute(stmt)).scalars().all())


async def get_report(db: AsyncSession, ctx: AuthContext, report_id: uuid.UUID) -> Report:
    report = await db.get(Report, report_id)
    if report is None or report.workspace_id != ctx.workspace_id:
        raise NotFoundError("Report not found")
    if report.project_id is None and ctx.allowed_project_ids is not None:
        raise NotFoundError("Report not found")
    if report.project_id is not None:
        ctx.assert_project(report.project_id)
    return report
