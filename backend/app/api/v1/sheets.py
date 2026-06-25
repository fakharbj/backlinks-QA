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
