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

    rows = (
        await db.execute(
            select(ImportRow)
            .where(ImportRow.import_id == import_id, ImportRow.status == ImportRowStatus.PENDING)
            .order_by(ImportRow.row_number.asc())
        )
    ).scalars().all()

    for row in rows:
        try:
            created_id = await _process_row(db, imp, row, seen_in_batch)
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
    db: AsyncSession, imp: Import, row: ImportRow, seen: set[tuple[str, str]]
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

    existing = (
        await db.execute(
            select(BacklinkRecord.id).where(
                BacklinkRecord.project_id == imp.project_id,
                BacklinkRecord.source_url_normalized == src.normalized,
                BacklinkRecord.target_url_normalized == tgt.normalized,
            )
        )
    ).scalar_one_or_none()
    if existing is not None:
        row.status = ImportRowStatus.DUPLICATE
        row.backlink_id = existing
        imp.duplicate_rows += 1
        return None

    vendor_id = None
    if data.get("vendor"):
        vendor_id = await resolve_vendor(db, imp.workspace_id, data["vendor"].strip())
    campaign_id = None
    if data.get("campaign"):
        campaign_id = await resolve_campaign(
            db, imp.workspace_id, imp.project_id, data["campaign"].strip()
        )

    backlink = BacklinkRecord(
        workspace_id=imp.workspace_id,
        project_id=imp.project_id,
        import_id=imp.id,
        vendor_id=vendor_id,
        campaign_id=campaign_id,
        source_page_url=source,
        target_url=target,
        expected_target_url=(data.get("expected_target_url") or target).strip(),
        expected_anchor_text=data.get("expected_anchor_text") or None,
        expected_rel=_parse_rel(data.get("expected_rel")),
        client_name=data.get("client_name") or None,
        cost=_parse_float(data.get("cost")),
        placement_date=_parse_date(data.get("placement_date")),
        expected_status=data.get("expected_status") or "live",
        notes=data.get("notes") or None,
        tags=_parse_tags(data.get("tags")),
        source_url_normalized=src.normalized,
        target_url_normalized=tgt.normalized,
        source_domain=src.registrable_domain,
        target_domain=tgt.registrable_domain,
        status=OverallStatus.PENDING,
        next_check_at=datetime.now(timezone.utc),
    )
    db.add(backlink)
    await db.flush()
    row.status = ImportRowStatus.IMPORTED
    row.backlink_id = backlink.id
    imp.imported_rows += 1
    return backlink.id


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
