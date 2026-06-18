"""Report endpoints: create (async generation), list, status, download."""

from __future__ import annotations

import uuid

from fastapi import APIRouter, Depends, status
from starlette.responses import StreamingResponse

from app.core.config import settings
from app.core.deps import AuthContext, AuthCtx, DbSession, ReadSession, require
from app.core.errors import ValidationAppError
from app.core.rbac import Permission
from app.integrations.storage import get_bytes_async
from app.models.enums import AuditAction, ReportStatus
from app.schemas.report import ReportCreate, ReportOut
from app.services import audit_service, report_service

_REPORT_MEDIA_TYPES = {
    "pdf": "application/pdf",
    "csv": "text/csv",
    "xlsx": "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
}

router = APIRouter(prefix="/reports", tags=["reports"])


@router.post("", response_model=ReportOut, status_code=status.HTTP_202_ACCEPTED)
async def create_report(
    payload: ReportCreate, db: DbSession,
    ctx: AuthContext = Depends(require(Permission.EXPORT_REPORTS)),
) -> ReportOut:
    if payload.project_id is not None:
        ctx.assert_project(payload.project_id)
    report = await report_service.create_report(db, ctx, payload)
    await audit_service.record(
        db, action=AuditAction.EXPORT, actor_user_id=ctx.user.id, workspace_id=ctx.workspace_id,
        entity_type="report", entity_id=report.id, summary=f"Report {payload.report_type.value}",
    )
    await db.commit()

    from app.workers.dispatch import enqueue_report

    enqueue_report(report.id)
    return ReportOut.model_validate(report)


@router.get("", response_model=list[ReportOut])
async def list_reports(ctx: AuthCtx, db: ReadSession) -> list[ReportOut]:
    return [ReportOut.model_validate(r) for r in await report_service.list_reports(db, ctx)]


@router.get("/{report_id}", response_model=ReportOut)
async def get_report(report_id: uuid.UUID, ctx: AuthCtx, db: ReadSession) -> ReportOut:
    return ReportOut.model_validate(await report_service.get_report(db, ctx, report_id))


@router.get("/{report_id}/download")
async def download_report(report_id: uuid.UUID, ctx: AuthCtx, db: ReadSession) -> StreamingResponse:
    report = await report_service.get_report(db, ctx, report_id)
    if report.status is not ReportStatus.COMPLETED or not report.file_key:
        raise ValidationAppError("Report is not ready for download")

    data = await get_bytes_async(settings.S3_BUCKET_REPORTS, report.file_key)
    fmt = report.format.value if hasattr(report.format, "value") else str(report.format)
    safe = (report.title or "report").strip().replace("/", "-").replace(" ", "_") or "report"
    return StreamingResponse(
        iter([data]),
        media_type=_REPORT_MEDIA_TYPES.get(fmt, "application/octet-stream"),
        headers={"Content-Disposition": f'attachment; filename="{safe}.{fmt}"'},
    )
