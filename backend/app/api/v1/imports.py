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
from app.services import (
    audit_service,
    batch_review_service,
    import_parse,
    project_service,
)

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


def _mapped_rows(
    headers: list[str], rows: list[dict[str, str]], mapping: dict[str, str] | None
) -> list[dict[str, str]]:
    """Apply the column mapping (user-chosen or auto) so the review batch
    stages canonical import fields, exactly like ``stage_rows`` would."""
    effective = mapping or import_parse.auto_map(headers)
    return [import_parse.apply_mapping(raw, effective) for raw in rows]


def _staged_response(batch) -> dict:
    """What the Imports desk shows the moment a review batch is created."""
    c = batch.counters or {}
    return {
        "batch_id": str(batch.id),
        "seq": batch.seq,
        "total": int((batch.totals or {}).get("total", 0)),
        "new": int(c.get("new", 0)),
        "existing": int(c.get("existing", 0)),
        "duplicate": int(c.get("duplicate", 0)),
        "invalid": int(c.get("invalid", 0)),
        "message": f"Review batch #B-{batch.seq} created — nothing is imported until you approve it",
    }


@router.post("/file", status_code=status.HTTP_202_ACCEPTED)
async def import_file(
    db: DbSession,
    project_id: uuid.UUID = Form(...),
    column_mapping: str | None = Form(default=None),
    file: UploadFile = File(...),
    ctx: AuthContext = Depends(require(Permission.IMPORT_BACKLINKS)),
) -> dict:
    """Stage a CSV/XLSX into a review batch (0029) — links are QA-testable in
    isolation and reach the project only when approved in the Batches desk."""
    await project_service.get_project(db, ctx, project_id)  # scope check
    data = await file.read()
    if len(data) > _MAX_UPLOAD_BYTES:
        raise ValidationAppError("File exceeds the 64 MiB limit")

    mapping = json.loads(column_mapping) if column_mapping else None
    name = (file.filename or "upload").lower()
    src = ImportSource.XLSX if name.endswith(".xlsx") else ImportSource.CSV
    headers, rows = (
        import_parse.parse_xlsx(data) if name.endswith(".xlsx") else import_parse.parse_csv(data)
    )
    if not rows:
        raise ValidationAppError("No rows found in the file")

    # Keep the original upload for the audit trail (referenced from batch meta).
    key = f"{ctx.workspace_id}/{uuid.uuid4().hex}-{name}"
    await put_bytes_async(
        settings.S3_BUCKET_IMPORTS, key, data,
        "application/octet-stream",
    )
    batch = await batch_review_service.stage_link_import(
        db, ctx, project_id=project_id, rows=_mapped_rows(headers, rows, mapping),
        source=src, filename=file.filename,
    )
    batch.meta = {**(batch.meta or {}), "upload_key": key}
    await audit_service.record(
        db, action=AuditAction.IMPORT, actor_user_id=ctx.user.id, workspace_id=ctx.workspace_id,
        entity_type="batch", entity_id=batch.id,
        summary=f"Staged file {file.filename} for review (#B-{batch.seq})",
    )
    await db.commit()
    return _staged_response(batch)


@router.post("/paste", status_code=status.HTTP_202_ACCEPTED)
async def import_paste(
    payload: PasteImportRequest, db: DbSession,
    ctx: AuthContext = Depends(require(Permission.IMPORT_BACKLINKS)),
) -> dict:
    """Stage pasted links into a review batch (0029) — same isolation as file
    imports: QA-test first, approve what you keep."""
    await project_service.get_project(db, ctx, payload.project_id)
    headers, rows = import_parse.parse_paste(payload.text)
    if not rows:
        raise ValidationAppError("No rows found in pasted text")

    batch = await batch_review_service.stage_link_import(
        db, ctx, project_id=payload.project_id,
        rows=_mapped_rows(headers, rows, payload.column_mapping),
        source=ImportSource.PASTE,
    )
    await audit_service.record(
        db, action=AuditAction.IMPORT, actor_user_id=ctx.user.id, workspace_id=ctx.workspace_id,
        entity_type="batch", entity_id=batch.id,
        summary=f"Staged pasted links for review (#B-{batch.seq})",
    )
    await db.commit()
    return _staged_response(batch)


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


@router.get("/{import_id}/errors.json")
async def list_errors(
    import_id: uuid.UUID, ctx: AuthCtx, db: ReadSession,
    limit: int = 200, offset: int = 0,
) -> dict:
    """In-app error report: the failed rows with their original cells, viewable
    without downloading anything."""
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
            .limit(max(1, min(limit, 500)))
            .offset(max(0, offset))
        )
    ).scalars().all()
    return {
        "total_errors": imp.error_rows,
        "rows": [
            {"row_number": r.row_number, "error": r.error, "raw": r.raw or {}}
            for r in rows
        ],
    }


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
