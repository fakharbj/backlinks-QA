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
from app.models.settings import Setting
from app.models.sheets import SheetSource
from app.schemas.sheet import (
    SheetConfigOut,
    SheetsApiLimitIn,
    SheetsApiLimitOut,
    SheetSourceOut,
    SheetSyncResponse,
    SheetTabOut,
    SheetTabUpdate,
)
from app.services import audit_service, sheet_sync_service

router = APIRouter(prefix="/sheets", tags=["sheets"])

_API_LIMIT_KEY = "sheets_reads_per_min"


def _mirror_limit_to_redis(val: int) -> None:
    """Write the limit to the same Redis the worker's read-throttle checks
    (google_sheets.reads_per_min). Best-effort — never fails the request."""
    try:
        import redis  # sync client on the broker Redis (what the throttle reads)

        redis.Redis.from_url(str(settings.CELERY_BROKER_URL), socket_timeout=3).set(
            "ls:cfg:sheets_reads_per_min", str(int(val))
        )
    except Exception:  # noqa: BLE001
        pass


@router.get("/api-limit", response_model=SheetsApiLimitOut)
async def get_api_limit(ctx: AuthCtx, db: ReadSession) -> SheetsApiLimitOut:
    """Current Sheets API read cap (reads/min). Persisted per workspace; also
    mirrored to Redis so the worker throttle picks it up even after a cache flush."""
    import asyncio

    row = (
        await db.execute(
            select(Setting).where(
                Setting.workspace_id == ctx.workspace_id, Setting.key == _API_LIMIT_KEY
            )
        )
    ).scalar_one_or_none()
    val = settings.GOOGLE_SHEETS_READS_PER_MIN
    if row is not None and isinstance(row.value, dict) and row.value.get("value") is not None:
        try:
            val = int(row.value["value"])
        except (TypeError, ValueError):
            pass
    await asyncio.to_thread(_mirror_limit_to_redis, val)  # write-through (survives flush)
    return SheetsApiLimitOut(reads_per_min=val, default=settings.GOOGLE_SHEETS_READS_PER_MIN)


@router.put("/api-limit", response_model=SheetsApiLimitOut)
async def put_api_limit(
    payload: SheetsApiLimitIn, db: DbSession,
    ctx: AuthContext = Depends(require(Permission.MANAGE_INTEGRATIONS)),
) -> SheetsApiLimitOut:
    import asyncio

    val = max(0, min(300, int(payload.reads_per_min)))
    row = (
        await db.execute(
            select(Setting).where(
                Setting.workspace_id == ctx.workspace_id, Setting.key == _API_LIMIT_KEY
            )
        )
    ).scalar_one_or_none()
    if row is None:
        db.add(Setting(workspace_id=ctx.workspace_id, key=_API_LIMIT_KEY, value={"value": val}, is_secret=False))
    else:
        row.value = {"value": val}
    await audit_service.record(
        db, action=AuditAction.UPDATE, actor_user_id=ctx.user.id, workspace_id=ctx.workspace_id,
        entity_type="setting", entity_id=ctx.workspace_id, summary=f"Sheets API read limit → {val}/min",
    )
    await db.commit()
    await asyncio.to_thread(_mirror_limit_to_redis, val)
    return SheetsApiLimitOut(reads_per_min=val, default=settings.GOOGLE_SHEETS_READS_PER_MIN)


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
    return SheetSyncResponse(
        message="Discovering projects from the main sheet (names + sheet links + tabs). "
        "Set each project's tab mapping, then click Sync on a project to pull its links."
    )


@router.post("/sync-all", response_model=SheetSyncResponse, status_code=202)
async def sync_all(
    db: DbSession,
    ctx: AuthContext = Depends(require(Permission.IMPORT_BACKLINKS)),
) -> SheetSyncResponse:
    """Queue a sync for EVERY connected project sheet (manual trigger only).
    The sheets.sync queue processes them one at a time (the sequential-sync
    setting), so the read-rate limit is respected; live per-sheet progress shows
    in the Sheets desk exactly like single syncs (batches kind=sheet_sync)."""
    from sqlalchemy import select as _select

    from app.workers.tasks.sheets import sync_project_sheet

    sources = (
        await db.execute(
            _select(SheetSource).where(SheetSource.workspace_id == ctx.workspace_id)
        )
    ).scalars().all()
    if not sources:
        raise ValidationAppError("No project sheets are connected yet — run Discover first.")
    await audit_service.record(
        db, action=AuditAction.IMPORT, actor_user_id=ctx.user.id, workspace_id=ctx.workspace_id,
        entity_type="sheet_sync", entity_id=ctx.workspace_id,
        summary=f"Sync ALL sheets started ({len(sources)} sheets)",
    )
    await db.commit()
    for src in sources:
        sync_project_sheet.apply_async(args=[str(src.id)], queue="sheets.sync")
    return SheetSyncResponse(
        message=f"Syncing all {len(sources)} sheets — they run one at a time to respect the "
        "Google API limit. Live progress appears below; each sheet reports its own result."
    )


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


async def _resolve_mapping_tab(db, sheet_id: uuid.UUID, tab_id):
    """The tab the mapping UI is operating on: the given ``tab_id`` if valid for
    this sheet, else the first import-enabled tab by name, else the first tab."""
    from app.models.sheet_tab import GoogleSheetTab

    if tab_id:
        try:
            tid = uuid.UUID(str(tab_id))
        except (ValueError, TypeError):
            tid = None
        if tid is not None:
            tab = await db.get(GoogleSheetTab, tid)
            if tab is not None and tab.sheet_source_id == sheet_id:
                return tab
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
    if tab is not None:
        return tab
    return (
        await db.execute(
            select(GoogleSheetTab)
            .where(GoogleSheetTab.sheet_source_id == sheet_id)
            .order_by(GoogleSheetTab.tab_name)
        )
    ).scalars().first()


def _project_default_target(project) -> str | None:
    """The project's default target: ``target_urls[0]`` else the main domain."""
    if project is None:
        return None
    if project.target_urls:
        return project.target_urls[0]
    if project.target_domain:
        return f"https://{project.target_domain}"
    return None


@router.get("/{sheet_id}/mapping")
async def get_mapping(
    sheet_id: uuid.UUID, ctx: AuthCtx, db: ReadSession, tab_id: str | None = None,
) -> dict:
    """Column-mapping settings + a live preview for ONE tab: the tab's real
    headers and sample rows (read live at its header row), the mapping in effect
    (per-tab override → source default → auto-detected), the canonical fields and
    field metadata, per-tab constants, and the write-back column choices."""
    import asyncio

    from app.models.project import Project
    from app.services import import_parse
    from app.services.sheet_sync_service import _WRITEBACK_HEADERS

    source = await db.get(SheetSource, sheet_id)
    if source is None or source.workspace_id != ctx.workspace_id:
        raise NotFoundError("Sheet source not found")

    from app.models.sheet_tab import GoogleSheetTab

    all_tabs = (
        await db.execute(
            select(GoogleSheetTab)
            .where(GoogleSheetTab.sheet_source_id == sheet_id)
            .order_by(GoogleSheetTab.tab_name)
        )
    ).scalars().all()
    tab = await _resolve_mapping_tab(db, sheet_id, tab_id)

    headers: list[str] = []
    rows: list[dict] = []
    header_error: str | None = None
    if tab is not None:
        try:
            headers, rows = await asyncio.to_thread(
                google_sheets.read_project_sheet_cached, source.spreadsheet_id,
                tab.tab_name, (tab.header_row or 1),
            )
        except Exception as exc:  # noqa: BLE001 — mapping UI still works without live headers
            header_error = str(exc)[:300]
        # Snapshot the columns for drift detection — strictly best-effort, in its
        # own transaction so a write failure never masks a good live preview.
        if headers:
            try:
                tab.headers_snapshot = headers
                await db.commit()
            except Exception:  # noqa: BLE001
                await db.rollback()
    else:
        header_error = "No tabs detected yet — run a sync to discover the sheet's tabs."

    auto = import_parse.auto_map(headers) if headers else {}
    tab_mapping = dict(tab.column_mapping) if (tab and tab.column_mapping) else {}
    source_mapping = dict(source.column_mapping or {})
    effective = tab_mapping or source_mapping or auto

    project = await db.get(Project, source.project_id)
    project_target = _project_default_target(project)

    field_constants = dict(tab.field_constants) if (tab and tab.field_constants) else {}
    required_ok = bool(
        effective and "source_page_url" in effective.values()
    ) or ("source_page_url" in field_constants)

    return {
        "tabs": [
            {"id": str(t.id), "tab_name": t.tab_name, "import_enabled": t.import_enabled}
            for t in all_tabs
        ],
        "tab_id": str(tab.id) if tab is not None else None,
        "headers": headers,
        "header_error": header_error,
        "sample_rows": rows[:8],
        "row_count": len(rows),
        "mapping": effective,
        "tab_mapping": tab_mapping,
        "source_mapping": source_mapping,
        "is_manual": bool(tab_mapping or source_mapping),
        "auto": import_parse.auto_map_report(headers) if headers else
        {"mapping": {}, "matched": [], "unmatched": []},
        "field_constants": field_constants,
        "header_row": (tab.header_row or 1) if tab is not None else 1,
        "fields": import_parse.CANONICAL_FIELDS,
        "field_meta": import_parse.CANONICAL_FIELD_META,
        "writeback_options": list(_WRITEBACK_HEADERS),
        "writeback_columns": (source.writeback_columns or {}).get("columns")
        or list(_WRITEBACK_HEADERS),
        "project_target": project_target,
        "required_ok": required_ok,
    }


@router.put("/{sheet_id}/mapping")
async def put_mapping(
    sheet_id: uuid.UUID, payload: dict, db: DbSession,
    ctx: AuthContext = Depends(require(Permission.IMPORT_BACKLINKS)),
) -> dict:
    """Save mapping/constants/header-row for a tab, the source-level default, or
    every import-enabled tab (``apply_to``: tab | source | all_tabs). Write-back
    column selection is always source-level. An empty mapping restores
    auto-detection."""
    from app.models.sheet_tab import GoogleSheetTab
    from app.services import import_parse
    from app.services.sheet_sync_service import _WRITEBACK_HEADERS

    source = await db.get(SheetSource, sheet_id)
    if source is None or source.workspace_id != ctx.workspace_id:
        raise NotFoundError("Sheet source not found")

    valid_fields = set(import_parse.CANONICAL_FIELDS)
    apply_to = str(payload.get("apply_to") or "tab")
    if apply_to not in ("tab", "source", "all_tabs"):
        apply_to = "tab"

    cleaned_mapping: dict | None = None
    raw_mapping = payload.get("column_mapping")
    if isinstance(raw_mapping, dict):
        cleaned_mapping = {
            str(h)[:200]: f for h, f in raw_mapping.items() if f in valid_fields
        }

    cleaned_constants: dict | None = None
    raw_constants = payload.get("field_constants")
    if isinstance(raw_constants, dict):
        cleaned_constants = {
            k: v for k, v in raw_constants.items() if k in valid_fields
        }

    header_row = payload.get("header_row")
    if header_row is not None:
        try:
            header_row = max(1, min(50, int(header_row)))
        except (ValueError, TypeError):
            header_row = None

    if apply_to == "source":
        if cleaned_mapping is not None:
            source.column_mapping = cleaned_mapping
    elif apply_to == "all_tabs":
        tabs = (
            await db.execute(
                select(GoogleSheetTab).where(
                    GoogleSheetTab.sheet_source_id == sheet_id,
                    GoogleSheetTab.import_enabled.is_(True),
                )
            )
        ).scalars().all()
        for t in tabs:
            if cleaned_mapping is not None:
                t.column_mapping = cleaned_mapping
            if cleaned_constants is not None:
                t.field_constants = cleaned_constants
            if header_row is not None:
                t.header_row = header_row
    else:  # tab
        tab = await _resolve_mapping_tab(db, sheet_id, payload.get("tab_id"))
        if tab is None:
            raise ValidationAppError("No tab to save mapping for — run a sync first.")
        if cleaned_mapping is not None:
            tab.column_mapping = cleaned_mapping
        if cleaned_constants is not None:
            tab.field_constants = cleaned_constants
        if header_row is not None:
            tab.header_row = header_row

    raw_wb = payload.get("writeback_columns")
    if isinstance(raw_wb, list):
        chosen = [c for c in raw_wb if c in _WRITEBACK_HEADERS]
        source.writeback_columns = {"columns": chosen or list(_WRITEBACK_HEADERS)}

    await audit_service.record(
        db, action=AuditAction.UPDATE, actor_user_id=ctx.user.id, workspace_id=ctx.workspace_id,
        entity_type="sheet_mapping", entity_id=sheet_id,
        summary=f"Column mapping updated ({apply_to}) for '{source.project_name}'",
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
