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

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import settings
from app.core.logging import get_logger
from app.integrations import google_sheets
from app.models.backlink import BacklinkRecord
from app.models.enums import ImportSource, ImportStatus
from app.models.imports import Import
from app.models.project import Project
from app.models.sheets import SheetSource
from app.services import import_parse, import_service

log = get_logger("services.sheet_sync")


def _now() -> datetime:
    return datetime.now(timezone.utc)


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


async def sync_project(db: AsyncSession, sheet_source_id: uuid.UUID) -> dict:
    """Sync one project sheet into the system via the import pipeline."""
    source = await db.get(SheetSource, sheet_source_id)
    if source is None:
        return {"error": "sheet source not found"}

    source.last_sync_status = "running"
    source.last_sync_error = None
    await db.commit()

    try:
        headers, rows = await asyncio.to_thread(
            google_sheets.read_project_sheet, source.spreadsheet_id, source.sheet_tab
        )
    except Exception as exc:  # noqa: BLE001 - one bad sheet must not stop the rest
        log.warning("project_sheet_read_failed", sheet_source_id=str(sheet_source_id),
                    error=repr(exc))
        source.last_sync_status = "error"
        source.last_sync_error = str(exc)[:1000]
        source.last_synced_at = _now()
        await db.commit()
        return {"error": str(exc)}

    # Per-sheet override mapping if set, else auto-map by header synonyms.
    mapping = dict(source.column_mapping) if source.column_mapping else import_parse.auto_map(headers)

    imp = Import(
        workspace_id=source.workspace_id,
        project_id=source.project_id,
        created_by=None,
        source=ImportSource.GOOGLE_SHEETS,
        sheet_source_id=source.id,
        filename=f"sheet:{source.spreadsheet_id}",
        column_mapping=mapping,
        status=ImportStatus.PENDING,
    )
    db.add(imp)
    await db.flush()
    await import_service.stage_rows(db, imp, rows)
    await db.commit()

    new_ids = await import_service.process(db, imp.id)

    refreshed = await db.get(Import, imp.id)
    source.last_synced_at = _now()
    source.last_sync_status = "ok"
    source.last_sync_error = None
    source.last_sync_import_id = imp.id
    source.row_count = len(rows)
    source.imported_count = refreshed.imported_rows if refreshed else len(new_ids)
    source.updated_count = (refreshed.imported_rows - len(new_ids)) if refreshed else 0
    await db.commit()

    return {
        "rows": len(rows),
        "new": len(new_ids),
        "new_ids": [str(i) for i in new_ids],
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

    values_by_row: dict[int, list] = {}
    for bl in backlinks:
        try:
            sheet_row = int(bl.sheet_row_ref) + 1  # +1 for the header row
        except (TypeError, ValueError):
            continue
        status = (bl.override_status or bl.status)
        values_by_row[sheet_row] = [
            status.value if status else "",
            bl.score if bl.score is not None else "",
            bl.index_status or "unchecked",
            bl.duplicate_status or "unique",
            bl.last_checked_at.strftime("%Y-%m-%d %H:%M") if bl.last_checked_at else "",
        ]
    if not values_by_row:
        return {"rows": 0}

    try:
        result = await asyncio.to_thread(
            google_sheets.write_back,
            source.spreadsheet_id, source.sheet_tab, _WRITEBACK_HEADERS, values_by_row,
        )
    except Exception as exc:  # noqa: BLE001 - write-back failure must not crash
        log.warning("writeback_failed", sheet_source_id=str(sheet_source_id), error=repr(exc))
        return {"error": str(exc)}
    source.last_sync_error = None
    await db.commit()
    return result
