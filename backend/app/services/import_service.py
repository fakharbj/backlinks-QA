"""Import staging + resumable processing (PRD §8.3).

Rows are staged to ``import_rows`` first, so a crash mid-import resumes from the
last unprocessed row rather than re-reading the upload. Processing validates,
URL-normalizes, dedups (within the project), auto-creates vendors/campaigns, and
upserts ``backlink_records`` — returning the ids of newly created links to crawl.
"""

from __future__ import annotations

import uuid
from datetime import date, datetime, timezone

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.deps import AuthContext
from app.crawler.normalize import normalize_url
from app.models.backlink import BacklinkRecord
from app.models.user import User, WorkspaceMember
from app.services.catalog_helpers import resolve_campaign, resolve_vendor
from app.models.enums import (
    ImportRowStatus,
    ImportSource,
    ImportStatus,
    OverallStatus,
    RelType,
)
from app.models.imports import Import, ImportRow
from app.services.import_parse import apply_mapping

_REL_ALIASES = {
    "follow": RelType.DOFOLLOW, "dofollow": RelType.DOFOLLOW, "do-follow": RelType.DOFOLLOW,
    "nofollow": RelType.NOFOLLOW, "no-follow": RelType.NOFOLLOW,
    "sponsored": RelType.SPONSORED, "ugc": RelType.UGC, "": RelType.DOFOLLOW,
}
_DATE_FORMATS = ("%Y-%m-%d", "%d/%m/%Y", "%m/%d/%Y", "%d-%m-%Y", "%Y/%m/%d")


async def create_import(
    db: AsyncSession,
    ctx: AuthContext,
    *,
    project_id: uuid.UUID,
    source: ImportSource,
    filename: str | None = None,
    upload_key: str | None = None,
    column_mapping: dict[str, str] | None = None,
) -> Import:
    imp = Import(
        workspace_id=ctx.workspace_id,
        project_id=project_id,
        created_by=ctx.user.id,
        source=source,
        filename=filename,
        upload_key=upload_key,
        column_mapping=column_mapping or {},
        status=ImportStatus.PENDING,
    )
    db.add(imp)
    await db.flush()
    return imp


async def stage_rows(
    db: AsyncSession, imp: Import, raw_rows: list[dict[str, str]]
) -> None:
    """Project each raw row through the mapping and persist it for processing."""
    mapping = imp.column_mapping or {}
    for i, raw in enumerate(raw_rows, start=1):
        mapped = apply_mapping(raw, mapping) if mapping else raw
        db.add(
            ImportRow(
                import_id=imp.id,
                row_number=i,
                raw=raw,
                mapped=mapped,
                status=ImportRowStatus.PENDING,
            )
        )
    imp.total_rows = len(raw_rows)
    await db.flush()


async def process(db: AsyncSession, import_id: uuid.UUID, *, commit_every: int = 500) -> list[uuid.UUID]:  # noqa: E501
    imp = await db.get(Import, import_id)
    if imp is None:
        return []
    imp.status = ImportStatus.PROCESSING
    await db.flush()

    new_ids: list[uuid.UUID] = []
    seen_in_batch: set[tuple[str, str]] = set()
    processed = 0

    # Resolve the sheet "User" label to an app user when it matches an account
    # email. Built once per import (cheap) so we never query per row at 1M+ scale.
    user_map = await _workspace_user_map(db, imp.workspace_id)

    rows = (
        await db.execute(
            select(ImportRow)
            .where(ImportRow.import_id == import_id, ImportRow.status == ImportRowStatus.PENDING)
            .order_by(ImportRow.row_number.asc())
        )
    ).scalars().all()

    for row in rows:
        try:
            created_id = await _process_row(db, imp, row, seen_in_batch, user_map)
            if created_id is not None:
                new_ids.append(created_id)
        except Exception as exc:  # noqa: BLE001 - per-row isolation; never abort the import
            row.status = ImportRowStatus.ERROR
            row.error = str(exc)[:500]
            imp.error_rows += 1
        processed += 1
        imp.processed_rows = processed
        if processed % commit_every == 0:
            await db.commit()

    imp.status = (
        ImportStatus.COMPLETED if imp.error_rows == 0 else ImportStatus.PARTIAL
    )
    await db.commit()
    return new_ids


async def _process_row(
    db: AsyncSession,
    imp: Import,
    row: ImportRow,
    seen: set[tuple[str, str]],
    user_map: dict[str, uuid.UUID],
) -> uuid.UUID | None:
    data = row.mapped or {}
    source = (data.get("source_page_url") or "").strip()
    target = (data.get("target_url") or "").strip()
    if not source or not target:
        row.status = ImportRowStatus.ERROR
        row.error = "Missing source or target URL"
        imp.error_rows += 1
        return None

    src = normalize_url(source)
    tgt = normalize_url(target)
    if not src.valid:
        row.status = ImportRowStatus.ERROR
        row.error = f"Invalid source URL ({src.error})"
        imp.error_rows += 1
        return None
    if not tgt.valid:
        row.status = ImportRowStatus.ERROR
        row.error = f"Invalid target URL ({tgt.error})"
        imp.error_rows += 1
        return None

    key = (src.normalized, tgt.normalized)
    if key in seen:
        row.status = ImportRowStatus.DUPLICATE
        imp.duplicate_rows += 1
        return None
    seen.add(key)

    from_sheet = imp.source == ImportSource.GOOGLE_SHEETS
    vendor_id = (
        await resolve_vendor(db, imp.workspace_id, data["vendor"].strip())
        if data.get("vendor") else None
    )
    campaign_id = (
        await resolve_campaign(db, imp.workspace_id, imp.project_id, data["campaign"].strip())
        if data.get("campaign") else None
    )

    existing = (
        await db.execute(
            select(BacklinkRecord).where(
                BacklinkRecord.project_id == imp.project_id,
                BacklinkRecord.source_url_normalized == src.normalized,
                BacklinkRecord.target_url_normalized == tgt.normalized,
            )
        )
    ).scalar_one_or_none()

    if existing is not None:
        # From a sheet sync, the sheet owns the INPUT fields → update them in place
        # (QA/result fields are untouched). A CSV/manual import keeps the old
        # behaviour of treating an existing row as a duplicate.
        if from_sheet:
            _apply_input_fields(existing, data, imp, row, user_map, vendor_id, campaign_id)
            row.status = ImportRowStatus.IMPORTED
            row.backlink_id = existing.id
            imp.imported_rows += 1
        else:
            row.status = ImportRowStatus.DUPLICATE
            row.backlink_id = existing.id
            imp.duplicate_rows += 1
        return None

    backlink = BacklinkRecord(
        workspace_id=imp.workspace_id,
        project_id=imp.project_id,
        import_id=imp.id,
        source_page_url=source,
        target_url=target,
        source_url_normalized=src.normalized,
        target_url_normalized=tgt.normalized,
        source_domain=src.registrable_domain,
        target_domain=tgt.registrable_domain,
        status=OverallStatus.PENDING,
        next_check_at=datetime.now(timezone.utc),
    )
    _apply_input_fields(backlink, data, imp, row, user_map, vendor_id, campaign_id)
    db.add(backlink)
    await db.flush()
    row.status = ImportRowStatus.IMPORTED
    row.backlink_id = backlink.id
    imp.imported_rows += 1
    return backlink.id


def _apply_input_fields(
    bl: BacklinkRecord,
    data: dict,
    imp: Import,
    row: ImportRow,
    user_map: dict[str, uuid.UUID],
    vendor_id: uuid.UUID | None,
    campaign_id: uuid.UUID | None,
) -> None:
    """Set the SHEET-owned input fields on a backlink (create or re-sync update)."""
    target = (data.get("target_url") or bl.target_url or "").strip()
    if vendor_id is not None:
        bl.vendor_id = vendor_id
    if campaign_id is not None:
        bl.campaign_id = campaign_id
    bl.expected_target_url = (data.get("expected_target_url") or target).strip() or None
    if data.get("expected_anchor_text"):
        bl.expected_anchor_text = data["expected_anchor_text"]
    if data.get("expected_rel"):
        bl.expected_rel = _parse_rel(data.get("expected_rel"))
    if data.get("client_name"):
        bl.client_name = data["client_name"]
    if data.get("cost") is not None and data.get("cost") != "":
        bl.cost = _parse_float(data.get("cost"))
    if data.get("placement_date"):
        bl.placement_date = _parse_date(data.get("placement_date"))
    if data.get("expected_status"):
        bl.expected_status = data["expected_status"]
    if data.get("notes"):
        bl.notes = data["notes"]
    if data.get("tags"):
        bl.tags = _parse_tags(data.get("tags"))

    # Sheet-sourced fields.
    label = (data.get("assigned_user_label") or "").strip()
    if label:
        bl.assigned_user_label = label
        resolved = user_map.get(label.lower())
        if resolved is not None:
            bl.assigned_user_id = resolved
    if data.get("employee_code"):
        bl.employee_code = str(data["employee_code"]).strip()
    if data.get("link_type"):
        bl.link_type = str(data["link_type"]).strip()[:60]
    if data.get("sheet_created_date"):
        bl.sheet_created_date = _parse_date(data.get("sheet_created_date"))
    if imp.sheet_source_id is not None:
        bl.source_sheet_id = imp.sheet_source_id
    bl.sheet_row_ref = str(row.row_number)


async def _workspace_user_map(db: AsyncSession, workspace_id: uuid.UUID) -> dict[str, uuid.UUID]:
    """Lowercased email → user id, for matching the sheet 'User' to an app account."""
    rows = (
        await db.execute(
            select(User.id, User.email)
            .join(WorkspaceMember, WorkspaceMember.user_id == User.id)
            .where(WorkspaceMember.workspace_id == workspace_id)
        )
    ).all()
    return {email.lower(): uid for uid, email in rows if email}


def _parse_rel(value: str | None) -> RelType:
    return _REL_ALIASES.get((value or "").strip().lower(), RelType.DOFOLLOW)


def _parse_float(value: str | None) -> float | None:
    if not value:
        return None
    try:
        return float(str(value).replace("$", "").replace(",", "").strip())
    except ValueError:
        return None


def _parse_date(value: str | None) -> date | None:
    if not value:
        return None
    raw = str(value).strip()
    for fmt in _DATE_FORMATS:
        try:
            return datetime.strptime(raw, fmt).date()
        except ValueError:
            continue
    try:
        return datetime.fromisoformat(raw).date()
    except ValueError:
        return None


def _parse_tags(value: str | None) -> list[str]:
    if not value:
        return []
    return [t.strip() for t in str(value).replace(";", ",").split(",") if t.strip()]
