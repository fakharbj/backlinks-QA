"""Google Sheets endpoints: config, list connected sheets, trigger syncs."""

from __future__ import annotations

import uuid

from fastapi import APIRouter, Depends
from sqlalchemy import select

from app.core.config import settings
from app.core.deps import AuthContext, AuthCtx, DbSession, ReadSession, require
from app.core.errors import NotFoundError, ValidationAppError
from app.core.rbac import Permission
from app.integrations import google_sheets
from app.models.enums import AuditAction
from app.models.sheets import SheetSource
from app.schemas.sheet import (
    SheetConfigOut,
    SheetSourceOut,
    SheetSyncResponse,
    SheetTabOut,
    SheetTabUpdate,
)
from app.services import audit_service, sheet_sync_service

router = APIRouter(prefix="/sheets", tags=["sheets"])


@router.get("/config", response_model=SheetConfigOut)
async def get_config(
    ctx: AuthContext = Depends(require(Permission.MANAGE_INTEGRATIONS)),
) -> SheetConfigOut:
    return SheetConfigOut(
        enabled=google_sheets.is_enabled(),
        service_account_email=google_sheets.service_account_email(),
        main_sheet_id=settings.GOOGLE_MAIN_SHEET_ID,
    )


@router.get("", response_model=list[SheetSourceOut])
async def list_sheets(ctx: AuthCtx, db: ReadSession) -> list[SheetSourceOut]:
    rows = (
        await db.execute(
            select(SheetSource)
            .where(SheetSource.workspace_id == ctx.workspace_id)
            .order_by(SheetSource.project_name.asc())
        )
    ).scalars().all()
    return [SheetSourceOut.model_validate(r) for r in rows]


@router.post("/sync", response_model=SheetSyncResponse, status_code=202)
async def sync_main(
    db: DbSession,
    ctx: AuthContext = Depends(require(Permission.IMPORT_BACKLINKS)),
) -> SheetSyncResponse:
    if not google_sheets.is_enabled():
        raise ValidationAppError(
            "Google Sheets is not configured (set GOOGLE_SHEETS_ENABLED, the service "
            "account, and GOOGLE_MAIN_SHEET_ID, and share the sheet with the SA email)."
        )
    await audit_service.record(
        db, action=AuditAction.IMPORT, actor_user_id=ctx.user.id, workspace_id=ctx.workspace_id,
        entity_type="sheet_sync", entity_id=ctx.workspace_id, summary="Main sheet sync",
    )
    await db.commit()

    from app.workers.tasks.sheets import sync_main_sheet

    sync_main_sheet.apply_async(args=[str(ctx.workspace_id)], queue="sheets.sync")
    return SheetSyncResponse(message="Main sheet sync started — projects will sync shortly.")


@router.post("/{sheet_id}/sync", response_model=SheetSyncResponse, status_code=202)
async def sync_one(
    sheet_id: uuid.UUID, db: DbSession,
    ctx: AuthContext = Depends(require(Permission.IMPORT_BACKLINKS)),
) -> SheetSyncResponse:
    source = await db.get(SheetSource, sheet_id)
    if source is None or source.workspace_id != ctx.workspace_id:
        raise NotFoundError("Sheet source not found")

    from app.workers.tasks.sheets import sync_project_sheet

    sync_project_sheet.apply_async(args=[str(sheet_id)], queue="sheets.sync")
    return SheetSyncResponse(message=f"Sync started for '{source.project_name}'.")


@router.post("/{sheet_id}/writeback", response_model=SheetSyncResponse, status_code=202)
async def writeback_one(
    sheet_id: uuid.UUID, db: DbSession,
    ctx: AuthContext = Depends(require(Permission.EXPORT_REPORTS)),
) -> SheetSyncResponse:
    source = await db.get(SheetSource, sheet_id)
    if source is None or source.workspace_id != ctx.workspace_id:
        raise NotFoundError("Sheet source not found")

    from app.workers.tasks.sheets import writeback_project_sheet

    writeback_project_sheet.apply_async(args=[str(sheet_id)], queue="sheets.sync")
    return SheetSyncResponse(
        message=f"Writing QA/index results back to '{source.project_name}' (result columns only)."
    )


@router.get("/{sheet_id}/mapping")
async def get_mapping(sheet_id: uuid.UUID, ctx: AuthCtx, db: ReadSession) -> dict:
    """Column-mapping settings: the sheet's real headers (read live from the
    first enabled tab), the mapping in effect (manual override or auto-detected),
    the canonical fields available, and the write-back column choices."""
    import asyncio

    from app.models.sheet_tab import GoogleSheetTab
    from app.services import import_parse
    from app.services.sheet_sync_service import _WRITEBACK_HEADERS

    source = await db.get(SheetSource, sheet_id)
    if source is None or source.workspace_id != ctx.workspace_id:
        raise NotFoundError("Sheet source not found")

    headers: list[str] = []
    header_error: str | None = None
    try:
        tab = (
            await db.execute(
                select(GoogleSheetTab)
                .where(
                    GoogleSheetTab.sheet_source_id == sheet_id,
                    GoogleSheetTab.import_enabled.is_(True),
                )
                .order_by(GoogleSheetTab.tab_name)
            )
        ).scalars().first()
        headers, _rows = await asyncio.to_thread(
            google_sheets.read_project_sheet, source.spreadsheet_id,
            tab.tab_name if tab else None,
        )
    except Exception as exc:  # noqa: BLE001 — mapping UI still works without live headers
        header_error = str(exc)[:300]

    auto = import_parse.auto_map(headers) if headers else {}
    manual = dict(source.column_mapping or {})
    return {
        "headers": headers,
        "header_error": header_error,
        "mapping": manual or auto,
        "is_manual": bool(manual),
        "auto_mapping": auto,
        "fields": import_parse.CANONICAL_FIELDS,
        "writeback_options": list(_WRITEBACK_HEADERS),
        "writeback_columns": (source.writeback_columns or {}).get("columns")
        or list(_WRITEBACK_HEADERS),
    }


@router.put("/{sheet_id}/mapping")
async def put_mapping(
    sheet_id: uuid.UUID, payload: dict, db: DbSession,
    ctx: AuthContext = Depends(require(Permission.IMPORT_BACKLINKS)),
) -> dict:
    """Save manual column mapping ({header: field}) and/or the write-back column
    selection. An empty mapping restores auto-detection."""
    from app.services import import_parse
    from app.services.sheet_sync_service import _WRITEBACK_HEADERS

    source = await db.get(SheetSource, sheet_id)
    if source is None or source.workspace_id != ctx.workspace_id:
        raise NotFoundError("Sheet source not found")

    raw_mapping = payload.get("column_mapping")
    if isinstance(raw_mapping, dict):
        valid_fields = set(import_parse.CANONICAL_FIELDS)
        source.column_mapping = {
            str(h)[:200]: f for h, f in raw_mapping.items() if f in valid_fields
        }
    raw_wb = payload.get("writeback_columns")
    if isinstance(raw_wb, list):
        chosen = [c for c in raw_wb if c in _WRITEBACK_HEADERS]
        source.writeback_columns = {"columns": chosen or list(_WRITEBACK_HEADERS)}
    await audit_service.record(
        db, action=AuditAction.UPDATE, actor_user_id=ctx.user.id, workspace_id=ctx.workspace_id,
        entity_type="sheet_mapping", entity_id=sheet_id,
        summary=f"Column mapping updated for '{source.project_name}'",
    )
    await db.commit()
    return {"message": "Mapping saved — it will be used on the next sync."}


def _tab_out(t) -> SheetTabOut:
    return SheetTabOut(
        id=t.id, gid=t.gid, tab_name=t.tab_name, link_type_name=t.link_type_name,
        import_enabled=t.import_enabled, qa_enabled=t.qa_enabled, status=t.status,
        row_count=t.row_count,
    )


@router.get("/{sheet_id}/tabs", response_model=list[SheetTabOut])
async def list_sheet_tabs(sheet_id: uuid.UUID, ctx: AuthCtx, db: ReadSession) -> list[SheetTabOut]:
    return [_tab_out(t) for t in await sheet_sync_service.list_tabs(db, ctx, sheet_id)]


@router.patch("/tabs/{tab_id}", response_model=SheetTabOut)
async def update_sheet_tab(
    tab_id: uuid.UUID, payload: SheetTabUpdate, db: DbSession,
    ctx: AuthContext = Depends(require(Permission.IMPORT_BACKLINKS)),
) -> SheetTabOut:
    tab = await sheet_sync_service.update_tab(db, ctx, tab_id, payload)
    await db.commit()
    return _tab_out(tab)
