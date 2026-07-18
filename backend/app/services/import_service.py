"""Import staging + resumable processing (PRD §8.3).

Rows are staged to ``import_rows`` first, so a crash mid-import resumes from the
last unprocessed row rather than re-reading the upload. Processing validates,
URL-normalizes, dedups (within the project), auto-creates vendors/campaigns, and
upserts ``backlink_records`` — returning the ids of newly created links to crawl.
"""

from __future__ import annotations

import re
import uuid
from datetime import date, datetime, timezone

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import settings
from app.core.deps import AuthContext
from app.crawler.normalize import normalize_url
from app.models.backlink import BacklinkRecord
from app.models.link_identity import AssignmentHistory
from app.models.user import User, WorkspaceMember
from app.services import (
    canonical_service,
    conflict_service,
    duplicate_service,
    link_type_service,
    source_domain_service,
)
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

# A cell like "open.substack.com/pub/x" or "www.foo.com" is obviously a URL
# that lost its scheme (Sheets strips it on some pastes) — repair, don't error.
_DOMAINISH = re.compile(r"^(www\.)?[a-zA-Z0-9][a-zA-Z0-9-]{0,62}(\.[a-zA-Z0-9-]{1,63})+([/?#].*)?$")


def coerce_url_scheme(url: str) -> str:
    """Prepend https:// to scheme-less domain-like values so real links from
    sheets never fail with "unsupported_scheme". Anything with an explicit
    scheme (http, mailto, tel, …) or that doesn't look like a domain is
    returned unchanged (still validated downstream)."""
    # Accidental line breaks inside a pasted URL (a sheet cell wrapped mid-URL)
    # would otherwise fail validation — join the pieces; real text keeps its
    # spaces so titles/notes still read as non-URLs.
    u = (url or "").strip().replace("\r", "").replace("\n", "")
    if not u or ":" in u.split("/", 1)[0]:
        return u  # has a scheme (or a port-ish colon) — leave it alone
    if _DOMAINISH.match(u):
        return f"https://{u}"
    return u


def looks_like_url(value: str) -> bool:
    """True only when the (already coerced) value is actually crawlable. A
    source cell holding plain text — an article title, "Pending", a note —
    is normal sheet formatting: the row is IGNORED quietly, never an error."""
    v = (value or "").strip().lower()
    return "://" in v or v.startswith(("http:", "https:"))


_REL_ALIASES = {
    "follow": RelType.DOFOLLOW, "dofollow": RelType.DOFOLLOW, "do-follow": RelType.DOFOLLOW,
    "nofollow": RelType.NOFOLLOW, "no-follow": RelType.NOFOLLOW,
    "sponsored": RelType.SPONSORED, "ugc": RelType.UGC, "": RelType.DOFOLLOW,
}
_DATE_FORMATS = (
    "%Y-%m-%d", "%d/%m/%Y", "%m/%d/%Y", "%d-%m-%Y", "%Y/%m/%d",
    # Month-name formats used by the production sheets, e.g. "30-April-2026",
    # "6 May 2026", "May 6, 2026", "30-Apr-2026" (full + abbreviated month).
    "%d-%B-%Y", "%d %B %Y", "%B %d, %Y", "%B %d %Y",
    "%d-%b-%Y", "%d %b %Y", "%b %d, %Y", "%b %d %Y",
    "%d.%m.%Y", "%Y.%m.%d",
    # Two-digit years, e.g. "01-Nov-24", "1/12/26".
    "%d-%b-%y", "%d-%B-%y", "%d/%m/%y", "%m/%d/%y", "%d %b %y",
)


def _is_gbp(link_type: str | None) -> bool:
    """GBP link types are fully excluded from the duplicate system (owner rule):
    any type whose NAME contains "GBP" (case-insensitive substring) never joins a
    link identity, is always duplicate_status='unique'/is_duplicate=False, and can
    never cause another link to be flagged. Only GBP is exempt."""
    return "gbp" in (link_type or "").lower()


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
    db: AsyncSession, imp: Import, raw_rows: list[dict[str, str]],
    *, default_link_type: str | None = None,
    field_constants: dict | None = None, default_target: str | None = None,
) -> None:
    """Project each raw row through the mapping and persist it for processing.

    ``default_link_type`` (the sub-sheet/tab name) is applied to rows that don't
    already carry a link type, so every row in a tab inherits that link type.
    ``field_constants`` (per-tab literals, e.g. link_type/vendor) fill a canonical
    field ONLY when the mapped row has no value for it. ``default_target`` fills
    ``target_url`` when the row (and its constants) leave it blank — bare-source
    rows inherit the project's target.
    """
    mapping = imp.column_mapping or {}
    for i, raw in enumerate(raw_rows, start=1):
        mapped = apply_mapping(raw, mapping) if mapping else dict(raw)
        if default_link_type and not str(mapped.get("link_type") or "").strip():
            mapped["link_type"] = default_link_type
        for k, v in (field_constants or {}).items():
            mapped.setdefault(k, v)
        if not mapped.get("target_url") and default_target:
            mapped["target_url"] = default_target
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
    dirty_identities: set[uuid.UUID] = set()
    dirty_canonicals: set[uuid.UUID] = set()
    identity_cache: dict[str, uuid.UUID] = {}
    canonical_cache: dict[str, uuid.UUID] = {}
    link_type_cache: dict = {}  # slug key → canonical LinkType row
    processed = 0

    # Resolve the sheet "User" label to an app user when it matches an account
    # email. Built once per import (cheap) so we never query per row at 1M+ scale.
    user_map = await _workspace_user_map(db, imp.workspace_id)
    # Target authority = the project's main domain (Phase 8): a row's target comes
    # from the project, not the sheet. Loaded once per import.
    project_domain = await _project_target_domain(db, imp.project_id)
    # Spelling-variant → canonical map (KEVIN/Keven → Kevin). Loaded once so a
    # re-sync of a still-misspelled sheet lands on the canonical and never re-splits.
    from app.services import employee_service

    label_aliases = await employee_service.alias_map(db, imp.workspace_id)

    rows = (
        await db.execute(
            select(ImportRow)
            .where(ImportRow.import_id == import_id, ImportRow.status == ImportRowStatus.PENDING)
            .order_by(ImportRow.row_number.asc())
        )
    ).scalars().all()

    for row in rows:
        try:
            created_id = await _process_row(
                db, imp, row, user_map, dirty_identities, identity_cache,
                canonical_cache, dirty_canonicals, link_type_cache, project_domain,
                label_aliases,
            )
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
            # Live progress for the Batches desk while a big file is importing
            # (fail-open; sheet sync has its own per-tab progress).
            if imp.batch_id is not None:
                from app.services import batch_service

                await batch_service.update(
                    imp.batch_id,
                    totals={
                        "total": imp.total_rows, "done": processed,
                        "ok": imp.imported_rows, "failed": imp.error_rows,
                    },
                    meta={"current_step": f"Importing rows ({processed}/{imp.total_rows})"},
                )

    # Recompute duplicate status for every identity this import touched.
    await duplicate_service.recompute(db, dirty_identities)
    # Group same-page backlinks (by canonical fingerprint) into conflict records so
    # stored duplicates surface in the Duplicates tab / filters (Phase 8 F10).
    await conflict_service.detect_for_canonicals(db, imp.workspace_id, dirty_canonicals)
    # Refresh source-domain aggregates so dashboards/ratios stay current (F11/F14).
    await source_domain_service.recompute(db, imp.workspace_id)

    imp.status = (
        ImportStatus.COMPLETED if imp.error_rows == 0 else ImportStatus.PARTIAL
    )
    await db.commit()
    return new_ids


async def _process_row(
    db: AsyncSession,
    imp: Import,
    row: ImportRow,
    user_map: dict[str, uuid.UUID],
    dirty_identities: set[uuid.UUID],
    identity_cache: dict[str, uuid.UUID],
    canonical_cache: dict[str, uuid.UUID],
    dirty_canonicals: set[uuid.UUID],
    link_type_cache: dict,
    project_domain: str | None,
    label_aliases: dict[str, str],
) -> uuid.UUID | None:
    data = row.mapped or {}
    source = coerce_url_scheme((data.get("source_page_url") or "").strip())
    # The project's main domain is the target for all its links (Phase 8). The sheet
    # 'target' column is only a fallback for projects with no main domain configured.
    target = f"https://{project_domain}/" if project_domain else coerce_url_scheme(
        (data.get("target_url") or "").strip()
    )
    if not looks_like_url(source):
        # No URL in the source cell — empty, a heading/spacer, or plain text
        # like an article title. NORMAL sheet formatting (owner rule): ignore
        # it quietly — green, never an error, never "partly failed".
        row.status = ImportRowStatus.SKIPPED
        row.error = None
        imp.skipped_rows = (imp.skipped_rows or 0) + 1
        return None
    if not target:
        row.status = ImportRowStatus.ERROR
        row.error = "No target: set the project's main domain in Settings"
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

    from_sheet = imp.source == ImportSource.GOOGLE_SHEETS

    # Canonical identity (SHA-256 fingerprint) of the SOURCE page (Phase 8 F8/F10).
    canonical = await canonical_service.resolve_canonical(db, source, cache=canonical_cache)
    canonical_id = canonical.id if canonical is not None else None
    if canonical_id is not None:
        dirty_canonicals.add(canonical_id)
    vendor_id = (
        await resolve_vendor(db, imp.workspace_id, data["vendor"].strip())
        if data.get("vendor") else None
    )
    campaign_id = (
        await resolve_campaign(db, imp.workspace_id, imp.project_id, data["campaign"].strip())
        if data.get("campaign") else None
    )

    # Sheet rows are keyed by their sheet position (source_sheet_id + row number),
    # so a re-sync UPDATES the same row in place (idempotent). Two DIFFERENT sheet
    # rows pointing at the same link are stored as SEPARATE backlinks — duplicates
    # are added (and grouped into a conflict), never silently skipped (Phase 8 F10).
    existing = None
    if from_sheet and imp.sheet_source_id is not None:
        existing = (
            await db.execute(
                select(BacklinkRecord).where(
                    BacklinkRecord.source_sheet_id == imp.sheet_source_id,
                    BacklinkRecord.sheet_tab == imp.sheet_tab,
                    BacklinkRecord.sheet_row_ref == str(row.row_number),
                )
            )
        ).scalar_one_or_none()
    elif not from_sheet:
        # File/paste imports upsert by the link itself: the same (source, target)
        # in the same project refreshes the existing record instead of inserting
        # a duplicate copy (owners' re-import bug).
        existing = (
            await db.execute(
                select(BacklinkRecord)
                .where(
                    BacklinkRecord.workspace_id == imp.workspace_id,
                    BacklinkRecord.project_id == imp.project_id,
                    BacklinkRecord.source_url_normalized == src.normalized,
                    BacklinkRecord.target_url_normalized == tgt.normalized,
                )
                .order_by(BacklinkRecord.created_at.asc())
                .limit(1)
            )
        ).scalars().first()

    if existing is not None:
        # Sheet row drift: rows shifted in the sheet mean this position now holds
        # a DIFFERENT link. Repoint the record at the new URL and reset its QA —
        # the old verdict described the old page.
        if existing.source_url_normalized != src.normalized:
            existing.source_page_url = source
            existing.source_url_normalized = src.normalized
            existing.source_domain = src.registrable_domain
            existing.target_url = target
            existing.target_url_normalized = tgt.normalized
            existing.target_domain = tgt.registrable_domain
            existing.status = OverallStatus.PENDING
            existing.score = None
            existing.next_check_at = (
                datetime.now(timezone.utc) if settings.AUTO_QA_ON_IMPORT else None
            )
        old_label = existing.assigned_user_label
        _apply_input_fields(existing, data, imp, row, user_map, vendor_id, campaign_id, label_aliases)
        existing.canonical_url_id = canonical_id
        # Canonical catalog row: follows merge redirects, so the STORED name is the
        # corrected master (a still-misspelled sheet can't re-split a merged type).
        _clt = await link_type_service.resolve_canonical(
            db, imp.workspace_id, existing.link_type, link_type_cache
        )
        existing.link_type_id = _clt.id if _clt is not None else None
        if _clt is not None:
            existing.link_type = _clt.name[:60]
        if _is_gbp(existing.link_type):
            # GBP is excluded from the duplicate system (owner rule): detach from any
            # identity this row held, re-roll that identity so a former peer can fall
            # back to unique, and stamp this row unique. recompute() never touches a
            # NULL-identity row, so the verdict is set here.
            if existing.link_identity_id is not None:
                dirty_identities.add(existing.link_identity_id)
            existing.link_identity_id = None
            existing.duplicate_status = duplicate_service.UNIQUE
            existing.is_duplicate = False
            identity_id = None
        else:
            identity_id = await duplicate_service.resolve_identity(
                db, imp.workspace_id, src.normalized, tgt.registrable_domain, identity_cache
            )
            existing.link_identity_id = identity_id
            dirty_identities.add(identity_id)
        new_label = existing.assigned_user_label
        if old_label and new_label and old_label != new_label:
            db.add(
                AssignmentHistory(
                    workspace_id=imp.workspace_id, project_id=imp.project_id,
                    backlink_id=existing.id, link_identity_id=identity_id,
                    old_user_label=old_label, new_user_label=new_label, source="sheet",
                )
            )
            existing.assigned_at = datetime.now(timezone.utc)
        row.status = ImportRowStatus.IMPORTED
        row.backlink_id = existing.id
        imp.imported_rows += 1
        imp.updated_rows = (imp.updated_rows or 0) + 1
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
        canonical_url_id=canonical_id,
        status=OverallStatus.PENDING,
        # Discovery = insert time. Set ONLY on create (never on the re-sync
        # update branch above) so it records when the link first entered our DB.
        discovered_at=datetime.now(timezone.utc),
        # QA/stat checks are MANUAL by default: new links wait as "QA pending"
        # until someone starts a check (AUTO_QA_ON_IMPORT turns the old
        # check-immediately behavior back on).
        next_check_at=(datetime.now(timezone.utc) if settings.AUTO_QA_ON_IMPORT else None),
    )
    _apply_input_fields(backlink, data, imp, row, user_map, vendor_id, campaign_id, label_aliases)
    # First assignment on insert: record when the link got an owner.
    if backlink.assigned_user_label:
        backlink.assigned_at = datetime.now(timezone.utc)
    _clt = await link_type_service.resolve_canonical(
        db, imp.workspace_id, backlink.link_type, link_type_cache
    )
    backlink.link_type_id = _clt.id if _clt is not None else None
    if _clt is not None:
        backlink.link_type = _clt.name[:60]
    if _is_gbp(backlink.link_type):
        # GBP is excluded from the duplicate system (owner rule): never joins an
        # identity and is always unique.
        backlink.link_identity_id = None
        backlink.duplicate_status = duplicate_service.UNIQUE
        backlink.is_duplicate = False
    else:
        identity_id = await duplicate_service.resolve_identity(
            db, imp.workspace_id, src.normalized, tgt.registrable_domain, identity_cache
        )
        backlink.link_identity_id = identity_id
        dirty_identities.add(identity_id)
    db.add(backlink)
    await db.flush()
    row.status = ImportRowStatus.IMPORTED
    row.backlink_id = backlink.id
    imp.imported_rows += 1
    imp.new_rows = (imp.new_rows or 0) + 1
    return backlink.id


def _apply_input_fields(
    bl: BacklinkRecord,
    data: dict,
    imp: Import,
    row: ImportRow,
    user_map: dict[str, uuid.UUID],
    vendor_id: uuid.UUID | None,
    campaign_id: uuid.UUID | None,
    label_aliases: dict[str, str],
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

    # Sheet-sourced fields. Roll a spelling variant up to its canonical person so a
    # re-sync of the still-misspelled sheet stores the canonical label (no re-split).
    # Labels are stored LOWERCASE (owner rule): "Junius" and "junius" are the same
    # person — case can never create duplicate identities again.
    raw_label = (data.get("assigned_user_label") or "").strip()
    if raw_label:
        label = label_aliases.get(raw_label.lower(), raw_label)
        bl.assigned_user_label = label.strip().lower()[:200]
        resolved = user_map.get(label.lower()) or user_map.get(raw_label.lower())
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
    bl.sheet_tab = imp.sheet_tab
    bl.sheet_row_ref = str(row.row_number)


async def _project_target_domain(db: AsyncSession, project_id: uuid.UUID) -> str | None:
    """The project's main domain (primary first) — the target for all its links."""
    from app.models.project_settings import ProjectDomain

    return (
        await db.execute(
            select(ProjectDomain.domain)
            .where(ProjectDomain.project_id == project_id)
            .order_by(ProjectDomain.is_primary.desc(), ProjectDomain.domain.asc())
            .limit(1)
        )
    ).scalar_one_or_none()


async def _workspace_user_map(db: AsyncSession, workspace_id: uuid.UUID) -> dict[str, uuid.UUID]:
    """Lowercased email OR sheet-label → user id, for matching the sheet 'User'
    to an app account. Label entries come from the employee catalog (including
    auto-provisioned sheet users) and win over an email collision."""
    rows = (
        await db.execute(
            select(User.id, User.email)
            .join(WorkspaceMember, WorkspaceMember.user_id == User.id)
            .where(WorkspaceMember.workspace_id == workspace_id)
        )
    ).all()
    out = {email.lower(): uid for uid, email in rows if email}
    from app.models.employee import UserEmployeeMapping

    maps = (
        await db.execute(
            select(UserEmployeeMapping.sheet_user_label, UserEmployeeMapping.user_id).where(
                UserEmployeeMapping.workspace_id == workspace_id,
                UserEmployeeMapping.user_id.is_not(None),
            )
        )
    ).all()
    for label, uid in maps:
        if label:
            out[label.lower()] = uid
    return out


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
    today = datetime.now(timezone.utc).date()

    def _guard(d: date | None) -> date | None:
        # A placement / sheet date can never be in the future. Two-digit years
        # (e.g. "10-Nov-35" → 2035) or a mis-parsed cell would otherwise store a
        # bogus future date and push the dashboard trend axis out to that year.
        # Drop it (→ None) so the row falls back to created_at via coalesce.
        if d is None or d > today:
            return None
        return d

    for fmt in _DATE_FORMATS:
        try:
            return _guard(datetime.strptime(raw, fmt).date())
        except ValueError:
            continue
    try:
        return _guard(datetime.fromisoformat(raw).date())
    except ValueError:
        return None


def _parse_tags(value: str | None) -> list[str]:
    if not value:
        return []
    return [t.strip() for t in str(value).replace(";", ",").split(",") if t.strip()]
