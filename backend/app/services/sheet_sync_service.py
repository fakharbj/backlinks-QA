"""Google Sheets sync orchestration (Phase 2).

Two stages, both DB-side (network reads are delegated to ``integrations.google_sheets``
via threads):

  discover_projects()  reads the global main sheet, ensures a Project + SheetSource
                       per row, and returns the SheetSource ids to sync.
  sync_project()       reads one project sheet, stages it through the EXISTING import
                       pipeline (validate → normalize → dedup → upsert), updates the
                       SheetSource state, and returns the new backlink ids to crawl.

Source-of-truth rule: the sheet owns input fields; the DB owns QA/result fields.
Re-syncing an existing link updates only its input fields (handled in
``import_service``); QA verdicts are never overwritten.
"""

from __future__ import annotations

import asyncio
import re
import uuid
from datetime import datetime, timezone

from sqlalchemy import select, text
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import settings
from app.core.logging import get_logger
from app.integrations import google_sheets
from app.models.backlink import BacklinkRecord
from app.models.enums import ImportSource, ImportStatus
from app.models.imports import Import
from app.models.project import Project
from app.models.sheet_tab import GoogleSheetTab
from app.models.sheets import SheetSource
from app.services import import_parse, import_service

log = get_logger("services.sheet_sync")


def _now() -> datetime:
    return datetime.now(timezone.utc)


async def list_tabs(db: AsyncSession, ctx, sheet_source_id: uuid.UUID) -> list[GoogleSheetTab]:
    from app.core.errors import NotFoundError

    source = await db.get(SheetSource, sheet_source_id)
    if source is None or source.workspace_id != ctx.workspace_id:
        raise NotFoundError("Sheet source not found")
    return list(
        (
            await db.execute(
                select(GoogleSheetTab)
                .where(GoogleSheetTab.sheet_source_id == sheet_source_id)
                .order_by(GoogleSheetTab.tab_name.asc())
            )
        ).scalars().all()
    )


async def update_tab(db: AsyncSession, ctx, tab_id: uuid.UUID, payload) -> GoogleSheetTab:
    from app.core.errors import NotFoundError

    tab = await db.get(GoogleSheetTab, tab_id)
    if tab is None or tab.workspace_id != ctx.workspace_id:
        raise NotFoundError("Sheet tab not found")
    for field, value in payload.model_dump(exclude_unset=True).items():
        setattr(tab, field, value)
    await db.flush()
    return tab


def _slugify(name: str) -> str:
    slug = re.sub(r"[^a-z0-9]+", "-", name.lower()).strip("-")
    return (slug or "project")[:110]


async def discover_projects(db: AsyncSession, workspace_id: uuid.UUID) -> list[uuid.UUID]:
    """Read the main sheet; ensure Project + SheetSource per row; return ids to sync."""
    rows = await asyncio.to_thread(google_sheets.read_main_sheet)
    sheet_source_ids: list[uuid.UUID] = []
    for row in rows:
        name = (str(row.get(settings.GOOGLE_MAIN_PROJECT_COL, "")) or "").strip()
        url = (str(row.get(settings.GOOGLE_MAIN_URL_COL, "")) or "").strip()
        if not name or not url:
            continue
        spreadsheet_id = google_sheets.extract_spreadsheet_id(url)
        if not spreadsheet_id:
            log.warning("sheet_url_unparsable", project=name, url=url[:120])
            continue
        project = await _resolve_project(db, workspace_id, name)
        source = await _resolve_sheet_source(
            db, workspace_id, project.id, name, spreadsheet_id, url
        )
        sheet_source_ids.append(source.id)
    await db.commit()
    return sheet_source_ids


async def _resolve_project(db: AsyncSession, workspace_id: uuid.UUID, name: str) -> Project:
    project = (
        await db.execute(
            select(Project).where(Project.workspace_id == workspace_id, Project.name == name)
        )
    ).scalar_one_or_none()
    if project is not None:
        return project

    base = _slugify(name)
    slug = base
    suffix = 1
    while (
        await db.execute(
            select(Project.id).where(Project.workspace_id == workspace_id, Project.slug == slug)
        )
    ).scalar_one_or_none() is not None:
        suffix += 1
        slug = f"{base}-{suffix}"[:120]

    project = Project(workspace_id=workspace_id, name=name, slug=slug)
    db.add(project)
    await db.flush()
    return project


async def _resolve_sheet_source(
    db: AsyncSession,
    workspace_id: uuid.UUID,
    project_id: uuid.UUID,
    name: str,
    spreadsheet_id: str,
    url: str,
) -> SheetSource:
    source = (
        await db.execute(select(SheetSource).where(SheetSource.project_id == project_id))
    ).scalar_one_or_none()
    if source is None:
        source = SheetSource(
            workspace_id=workspace_id, project_id=project_id, project_name=name,
            spreadsheet_id=spreadsheet_id, source_url=url,
        )
        db.add(source)
        await db.flush()
    else:
        source.project_name = name
        source.spreadsheet_id = spreadsheet_id
        source.source_url = url
    return source


async def _sync_tabs(db, source, worksheets) -> dict:
    """Upsert a GoogleSheetTab per detected tab (by stable gid); mark vanished tabs
    missing. Returns ``{gid: GoogleSheetTab}``."""
    seen = {w["gid"] for w in worksheets}
    existing = {
        t.gid: t
        for t in (
            await db.execute(
                select(GoogleSheetTab).where(GoogleSheetTab.sheet_source_id == source.id)
            )
        ).scalars().all()
    }
    out: dict = {}
    for w in worksheets:
        tab = existing.get(w["gid"])
        if tab is None:
            tab = GoogleSheetTab(
                workspace_id=source.workspace_id, sheet_source_id=source.id,
                gid=w["gid"], tab_name=w["title"], link_type_name=w["title"], status="detected",
            )
            db.add(tab)
        else:
            tab.tab_name = w["title"]  # follow renames (gid is stable)
            tab.status = "detected"
        out[w["gid"]] = tab
    for gid, tab in existing.items():
        if gid not in seen:
            tab.status = "missing"  # keep the tab + its imported links; just flag it
    await db.flush()
    return out


async def sync_project(db: AsyncSession, sheet_source_id: uuid.UUID) -> dict:
    """Sync ALL sub-sheets (tabs) of a project spreadsheet. Each tab name = a link
    type; rows inherit it. Re-sync is idempotent per (tab, row)."""
    source = await db.get(SheetSource, sheet_source_id)
    if source is None:
        return {"error": "sheet source not found"}

    source.last_sync_status = "running"
    source.last_sync_error = None
    await db.commit()

    try:
        worksheets = await asyncio.to_thread(google_sheets.list_worksheets, source.spreadsheet_id)
    except Exception as exc:  # noqa: BLE001
        log.warning("sheet_tabs_read_failed", sheet_source_id=str(sheet_source_id), error=repr(exc))
        source.last_sync_status = "error"
        source.last_sync_error = str(exc)[:1000]
        source.last_synced_at = _now()
        await db.commit()
        return {"error": str(exc)}

    tabs = await _sync_tabs(db, source, worksheets)
    await db.commit()

    total_rows = 0
    total_imported = 0
    all_new: list[uuid.UUID] = []
    for ws in worksheets:
        tab = tabs[ws["gid"]]
        if not tab.import_enabled:
            continue
        try:
            headers, rows = await asyncio.to_thread(
                google_sheets.read_project_sheet, source.spreadsheet_id, ws["title"]
            )
        except Exception as exc:  # noqa: BLE001 - one bad tab must not stop the rest
            log.warning("tab_read_failed", tab=ws["title"], error=repr(exc))
            continue
        mapping = (
            dict(source.column_mapping) if source.column_mapping else import_parse.auto_map(headers)
        )
        imp = Import(
            workspace_id=source.workspace_id,
            project_id=source.project_id,
            created_by=None,
            source=ImportSource.GOOGLE_SHEETS,
            sheet_source_id=source.id,
            sheet_tab=ws["title"],
            filename=f"sheet:{source.spreadsheet_id}:{ws['title']}",
            column_mapping=mapping,
            status=ImportStatus.PENDING,
        )
        db.add(imp)
        await db.flush()
        await import_service.stage_rows(
            db, imp, rows, default_link_type=(tab.link_type_name or ws["title"])
        )
        await db.commit()
        new_ids = await import_service.process(db, imp.id)
        refreshed = await db.get(Import, imp.id)
        all_new.extend(new_ids)
        total_rows += len(rows)
        total_imported += refreshed.imported_rows if refreshed else len(new_ids)
        tab.row_count = len(rows)
        tab.last_synced_at = _now()
        source.last_sync_import_id = imp.id

    # Remove legacy single-tab rows (imported before multi-tab existed, sheet_tab NULL)
    # now superseded by the tab-aware imports above.
    await db.execute(
        text("DELETE FROM backlink_records WHERE source_sheet_id = :sid AND sheet_tab IS NULL"),
        {"sid": source.id},
    )

    source.last_synced_at = _now()
    source.last_sync_status = "ok"
    source.last_sync_error = None
    source.row_count = total_rows
    source.imported_count = total_imported
    source.updated_count = max(0, total_imported - len(all_new))
    await db.commit()

    return {
        "tabs": len([w for w in worksheets if tabs[w["gid"]].import_enabled]),
        "rows": total_rows,
        "new": len(all_new),
    }


# Result columns written back to the sheet (allow-list — never input columns).
_WRITEBACK_HEADERS = ["LS Status", "LS Score", "LS Index", "LS Duplicate", "LS Checked"]


async def writeback_project(db: AsyncSession, sheet_source_id: uuid.UUID) -> dict:
    """Write QA/index/duplicate result columns back into the project sheet."""
    source = await db.get(SheetSource, sheet_source_id)
    if source is None:
        return {"error": "sheet source not found"}

    backlinks = (
        await db.execute(
            select(BacklinkRecord).where(
                BacklinkRecord.source_sheet_id == source.id,
                BacklinkRecord.sheet_row_ref.is_not(None),
            )
        )
    ).scalars().all()

    # Group rows by their sub-sheet/tab so each tab is written back to itself.
    by_tab: dict[str | None, dict[int, list]] = {}
    for bl in backlinks:
        try:
            sheet_row = int(bl.sheet_row_ref) + 1  # +1 for the header row
        except (TypeError, ValueError):
            continue
        status = bl.override_status or bl.status
        by_tab.setdefault(bl.sheet_tab, {})[sheet_row] = [
            status.value if status else "",
            bl.score if bl.score is not None else "",
            bl.index_status or "unchecked",
            bl.duplicate_status or "unique",
            bl.last_checked_at.strftime("%Y-%m-%d %H:%M") if bl.last_checked_at else "",
        ]
    if not by_tab:
        return {"rows": 0}

    written = 0
    for tab, values_by_row in by_tab.items():
        if not values_by_row:
            continue
        try:
            await asyncio.to_thread(
                google_sheets.write_back,
                source.spreadsheet_id, tab, _WRITEBACK_HEADERS, values_by_row,
            )
            written += 1
        except Exception as exc:  # noqa: BLE001 - write-back failure must not crash
            log.warning("writeback_failed", tab=tab, error=repr(exc))
    source.last_sync_error = None
    await db.commit()
    return {"tabs_written": written}
