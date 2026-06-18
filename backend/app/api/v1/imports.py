"""Import endpoints: preview (mapping UI), file & paste ingest, status, errors."""

from __future__ import annotations

import csv
import io
import json
import uuid

from fastapi import APIRouter, Depends, File, Form, UploadFile, status
from sqlalchemy import select
from starlette.responses import StreamingResponse

from app.core.deps import AuthContext, AuthCtx, DbSession, ReadSession, require
from app.core.errors import ValidationAppError
from app.core.rbac import Permission
from app.integrations.storage import put_bytes_async
from app.core.config import settings
from app.models.enums import AuditAction, ImportSource
from app.models.imports import Import, ImportRow
from app.schemas.import_ import (
    ImportOut,
    ImportPreview,
    PasteImportRequest,
    PastePreviewRequest,
)
from app.schemas.common import IdResponse
from app.services import audit_service, import_parse, import_service, project_service

router = APIRouter(prefix="/imports", tags=["imports"])

_MAX_UPLOAD_BYTES = 64 * 1024 * 1024  # 64 MiB


def _preview(headers: list[str], rows: list[dict[str, str]]) -> ImportPreview:
    return ImportPreview(
        headers=headers,
        suggested_mapping=import_parse.auto_map(headers),
        sample_rows=rows[:10],
        row_count=len(rows),
    )


@router.post("/preview-file", response_model=ImportPreview)
async def preview_file(ctx: AuthCtx, file: UploadFile = File(...)) -> ImportPreview:
    data = await file.read()
    if len(data) > _MAX_UPLOAD_BYTES:
        raise ValidationAppError("File exceeds the 64 MiB limit")
    name = (file.filename or "").lower()
    headers, rows = (
        import_parse.parse_xlsx(data) if name.endswith(".xlsx") else import_parse.parse_csv(data)
    )
    return _preview(headers, rows)


@router.post("/preview-paste", response_model=ImportPreview)
async def preview_paste(payload: PastePreviewRequest, ctx: AuthCtx) -> ImportPreview:
    headers, rows = import_parse.parse_paste(payload.text)
    return _preview(headers, rows)


@router.post("/file", response_model=IdResponse, status_code=status.HTTP_202_ACCEPTED)
async def import_file(
    db: DbSession,
    project_id: uuid.UUID = Form(...),
    column_mapping: str | None = Form(default=None),
    file: UploadFile = File(...),
    ctx: AuthContext = Depends(require(Permission.IMPORT_BACKLINKS)),
) -> IdResponse:
    await project_service.get_project(db, ctx, project_id)  # scope check
    data = await file.read()
    if len(data) > _MAX_UPLOAD_BYTES:
        raise ValidationAppError("File exceeds the 64 MiB limit")

    mapping = json.loads(column_mapping) if column_mapping else None
    name = (file.filename or "upload").lower()
    src = ImportSource.XLSX if name.endswith(".xlsx") else ImportSource.CSV

    key = f"{ctx.workspace_id}/{uuid.uuid4().hex}-{name}"
    await put_bytes_async(
        settings.S3_BUCKET_IMPORTS, key, data,
        "application/octet-stream",
    )
    imp = await import_service.create_import(
        db, ctx, project_id=project_id, source=src, filename=file.filename,
        upload_key=key, column_mapping=mapping,
    )
    await audit_service.record(
        db, action=AuditAction.IMPORT, actor_user_id=ctx.user.id, workspace_id=ctx.workspace_id,
        entity_type="import", entity_id=imp.id, summary=f"Import file {file.filename}",
    )
    await db.commit()

    from app.workers.dispatch import enqueue_import

    enqueue_import(imp.id, parse_from_storage=True)
    return IdResponse(id=str(imp.id))


@router.post("/paste", response_model=IdResponse, status_code=status.HTTP_202_ACCEPTED)
async def import_paste(
    payload: PasteImportRequest, db: DbSession,
    ctx: AuthContext = Depends(require(Permission.IMPORT_BACKLINKS)),
) -> IdResponse:
    await project_service.get_project(db, ctx, payload.project_id)
    headers, rows = import_parse.parse_paste(payload.text)
    if not rows:
        raise ValidationAppError("No rows found in pasted text")

    imp = await import_service.create_import(
        db, ctx, project_id=payload.project_id, source=ImportSource.PASTE,
        column_mapping=payload.column_mapping or import_parse.auto_map(headers),
    )
    await import_service.stage_rows(db, imp, rows)
    await db.commit()

    from app.workers.dispatch import enqueue_import

    enqueue_import(imp.id, parse_from_storage=False)
    return IdResponse(id=str(imp.id))


@router.get("", response_model=list[ImportOut])
async def list_imports(ctx: AuthCtx, db: ReadSession, project_id: uuid.UUID | None = None):
    stmt = select(Import).where(Import.workspace_id == ctx.workspace_id)
    if project_id:
        ctx.assert_project(project_id)
        stmt = stmt.where(Import.project_id == project_id)
    elif ctx.allowed_project_ids is not None:
        stmt = stmt.where(Import.project_id.in_(ctx.allowed_project_ids or {uuid.uuid4()}))
    stmt = stmt.order_by(Import.created_at.desc()).limit(100)
    return [ImportOut.model_validate(i) for i in (await db.execute(stmt)).scalars().all()]


@router.get("/{import_id}", response_model=ImportOut)
async def get_import(import_id: uuid.UUID, ctx: AuthCtx, db: ReadSession) -> ImportOut:
    imp = await db.get(Import, import_id)
    if imp is None or imp.workspace_id != ctx.workspace_id:
        from app.core.errors import NotFoundError

        raise NotFoundError("Import not found")
    ctx.assert_project(imp.project_id)
    return ImportOut.model_validate(imp)


@router.get("/{import_id}/errors")
async def download_errors(import_id: uuid.UUID, ctx: AuthCtx, db: ReadSession):
    imp = await db.get(Import, import_id)
    if imp is None or imp.workspace_id != ctx.workspace_id:
        from app.core.errors import NotFoundError

        raise NotFoundError("Import not found")
    ctx.assert_project(imp.project_id)
    rows = (
        await db.execute(
            select(ImportRow)
            .where(ImportRow.import_id == import_id, ImportRow.error.is_not(None))
            .order_by(ImportRow.row_number)
        )
    ).scalars().all()

    buf = io.StringIO()
    writer = csv.writer(buf)
    writer.writerow(["row_number", "error", "raw"])
    for r in rows:
        writer.writerow([r.row_number, r.error, json.dumps(r.raw)])
    buf.seek(0)
    return StreamingResponse(
        iter([buf.getvalue()]),
        media_type="text/csv",
        headers={"Content-Disposition": f"attachment; filename=import-{import_id}-errors.csv"},
    )
