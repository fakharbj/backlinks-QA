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
        # Discover this project's tabs NOW (metadata only — no row read) so the
        # mapping UI is usable BEFORE any import. This lets the operator set the
        # mapping first and then run a SINGLE import sync, instead of syncing once
        # just to reveal the tabs and a second time to actually import.
        try:
            worksheets = await asyncio.to_thread(
                google_sheets.list_worksheets_cached, spreadsheet_id
            )
            await _sync_tabs(db, source, worksheets)
        except Exception as exc:  # noqa: BLE001 — tab discovery must not fail the run
            log.warning("discover_tabs_failed", project=name, error=repr(exc))
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


async def _auto_provision_users(db: AsyncSession, source: SheetSource, batch_id) -> int:
    """Owners' rule: a person named in a project's sheet becomes a system user
    automatically, scoped to that project (Viewer role — task view + leave
    requests). Matching is case-insensitive ("tony" and "Tony" are one person).
    A catalog mapping already linked to an account is respected as-is; an
    unlinked mapping (backfill rows) gets an account and is linked. New accounts
    start with a random unusable password; admins hand out access via Team →
    Reset password. Fail-open: provisioning must never fail a sync."""
    from app.services import batch_service

    if not settings.SHEETS_AUTO_CREATE_USERS:
        return 0
    created = 0
    try:
        # Auto-provisioned addresses use the company's branded domain when the
        # owners configured one (Settings → branding), else the built-in default.
        from app.services.branding_service import get_branding

        branding = await get_branding(db, source.workspace_id)
        domain = (
            (branding.get("company_domain") or "").strip().lower().lstrip("@")
            or "sheet-users.linksentinel.local"
        )
        labels = (
            await db.execute(
                text(
                    "SELECT DISTINCT assigned_user_label FROM backlink_records "
                    "WHERE project_id = :pid AND assigned_user_label IS NOT NULL "
                    "AND assigned_user_label <> '' ORDER BY 1 LIMIT 200"
                ),
                {"pid": source.project_id},
            )
        ).scalars().all()
        if not labels:
            return 0

        import secrets

        from app.core.rbac import Role
        from app.core.security import hash_password
        from app.models.employee import UserEmployeeMapping
        from app.models.enums import AuditAction
        from app.models.project import ProjectMember
        from app.models.user import User, WorkspaceMember
        from app.services import audit_service

        # One person per lowercased name: "Tony" and "tony" must never become
        # two accounts, and the whole workspace catalog matters (not just the
        # labels present in this one project).
        mapped_lc: dict[str, UserEmployeeMapping] = {}
        for m in (
            await db.execute(
                select(UserEmployeeMapping).where(
                    UserEmployeeMapping.workspace_id == source.workspace_id
                )
            )
        ).scalars().all():
            mapped_lc.setdefault(m.sheet_user_label.lower(), m)
            if m.user_id is not None:
                mapped_lc[m.sheet_user_label.lower()] = m

        async def _is_project_member(user_id: uuid.UUID) -> bool:
            return (
                await db.execute(
                    select(ProjectMember.id).where(
                        ProjectMember.project_id == source.project_id,
                        ProjectMember.user_id == user_id,
                    )
                )
            ).scalar_one_or_none() is not None

        async def _grant_project_access(user_id: uuid.UUID, label: str) -> None:
            member = (
                await db.execute(
                    select(WorkspaceMember).where(
                        WorkspaceMember.workspace_id == source.workspace_id,
                        WorkspaceMember.user_id == user_id,
                    )
                )
            ).scalar_one_or_none()
            # Only Viewers: their access is membership-driven. QA/TeamLead
            # visibility is managed by admins and must never be auto-narrowed.
            if member is None or member.role != Role.VIEWER:
                return
            if not await _is_project_member(user_id):
                db.add(ProjectMember(project_id=source.project_id, user_id=user_id, role=None))
                await batch_service.add_log(
                    batch_id,
                    f"“{label}” appears in this project's sheet — project access added "
                    "to their existing account.",
                )

        seen_lc: set[str] = set()
        ws8 = source.workspace_id.hex[:8]
        for label in labels:
            lc = label.lower()
            if lc in seen_lc:
                continue
            seen_lc.add(lc)
            existing = mapped_lc.get(lc)
            if existing is not None and existing.user_id is not None:
                await _grant_project_access(existing.user_id, label)
                continue

            # Deterministic per-workspace address (the label is a sheet name, not
            # an email) — reruns find the same account instead of duplicating it.
            slug = re.sub(r"[^a-z0-9]+", ".", lc).strip(".") or "user"
            email = f"{slug[:40]}.{ws8}@{domain}"
            user = (
                await db.execute(select(User).where(User.email == email))
            ).scalar_one_or_none()
            if user is None and domain != "sheet-users.linksentinel.local":
                # Accounts provisioned before the company domain was set live at
                # the legacy address — reuse them instead of minting duplicates.
                legacy_email = f"{slug[:40]}.{ws8}@sheet-users.linksentinel.local"
                user = (
                    await db.execute(select(User).where(User.email == legacy_email))
                ).scalar_one_or_none()
            if user is not None and not user.is_active:
                continue  # an admin deactivated this auto account — leave it be
            if user is None:
                # Argon2 is CPU-heavy — run it off the event loop.
                password_hash = await asyncio.to_thread(
                    hash_password, secrets.token_urlsafe(24)
                )
                user = User(
                    email=email,
                    full_name=label[:200],
                    password_hash=password_hash,
                    is_active=True,
                )
                db.add(user)
                await db.flush()
                db.add(
                    WorkspaceMember(
                        workspace_id=source.workspace_id, user_id=user.id, role=Role.VIEWER
                    )
                )
            if existing is not None:
                existing.user_id = user.id  # link the unlinked backfill mapping
            else:
                db.add(
                    UserEmployeeMapping(
                        workspace_id=source.workspace_id,
                        sheet_user_label=label,
                        user_id=user.id,
                    )
                )
            if not await _is_project_member(user.id):
                db.add(ProjectMember(project_id=source.project_id, user_id=user.id, role=None))
            # Attribute this project's existing rows (any case variant) to them.
            await db.execute(
                text(
                    "UPDATE backlink_records SET assigned_user_id = :uid "
                    "WHERE project_id = :pid AND lower(assigned_user_label) = :lbl "
                    "AND assigned_user_id IS NULL"
                ),
                {"uid": user.id, "pid": source.project_id, "lbl": lc},
            )
            await audit_service.record(
                db, action=AuditAction.CREATE, workspace_id=source.workspace_id,
                entity_type="user", entity_id=user.id,
                summary=f"Auto-added '{label}' from sheet sync (User role, project-scoped)",
            )
            created += 1
            await batch_service.add_log(
                batch_id,
                f"Auto-added user account for “{label}” (User role, access to this project "
                "only) — hand out a password from Team → Reset password.",
            )
        await db.commit()
        if created:
            log.info(
                "sheet_users_auto_provisioned",
                sheet_source_id=str(source.id), created=created,
            )
    except Exception as exc:  # noqa: BLE001 — user provisioning is best-effort
        log.warning("auto_provision_users_failed", error=repr(exc))
        await db.rollback()
    return created


async def sync_project(db: AsyncSession, sheet_source_id: uuid.UUID) -> dict:
    """Sync ALL sub-sheets (tabs) of a project spreadsheet. Each tab name = a link
    type; rows inherit it. Re-sync is idempotent per (tab, row). The whole run is
    a ``sheet_sync`` batch with per-tab progress + plain-English logs."""
    from app.services import batch_service

    source = await db.get(SheetSource, sheet_source_id)
    if source is None:
        return {"error": "sheet source not found"}

    source.last_sync_status = "running"
    source.last_sync_error = None
    await db.commit()

    sync_started = _now()
    batch_id = await batch_service.start(
        "sheet_sync", source.workspace_id, project_id=source.project_id,
        label=f"Sheet sync — {source.project_name}",
        meta={"sheet_source_id": str(source.id)},
    )

    try:
        worksheets = await asyncio.to_thread(google_sheets.list_worksheets_cached, source.spreadsheet_id)
    except Exception as exc:  # noqa: BLE001
        log.warning("sheet_tabs_read_failed", sheet_source_id=str(sheet_source_id), error=repr(exc))
        source.last_sync_status = "error"
        source.last_sync_error = str(exc)[:1000]
        source.last_synced_at = _now()
        await db.commit()
        await batch_service.add_log(batch_id, f"Could not open the spreadsheet: {exc}", level="error")
        await batch_service.finish(batch_id, status="failed", error=str(exc)[:500])
        return {"error": str(exc)}

    tabs = await _sync_tabs(db, source, worksheets)
    await db.commit()

    # The project's default target — used for bare-source rows that leave the
    # target blank. Computed once per sync (target_urls[0] else the main domain).
    project = await db.get(Project, source.project_id)
    default_target: str | None = None
    if project is not None:
        if project.target_urls:
            default_target = project.target_urls[0]
        elif project.target_domain:
            default_target = f"https://{project.target_domain}"

    enabled = [w for w in worksheets if tabs[w["gid"]].import_enabled]
    await batch_service.update(batch_id, totals={"total_tabs": len(enabled)})

    total_rows = 0
    total_imported = 0
    total_failed = 0
    total_skipped = 0
    done_tabs = 0
    all_new: list[uuid.UUID] = []
    for ws in enabled:
        tab = tabs[ws["gid"]]
        await batch_service.update(batch_id, meta={"current_step": f"Reading “{ws['title']}”"})
        try:
            headers, rows = await asyncio.to_thread(
                google_sheets.read_project_sheet_cached, source.spreadsheet_id, ws["title"],
                (tab.header_row or 1),
            )
        except Exception as exc:  # noqa: BLE001 - one bad tab must not stop the rest
            log.warning("tab_read_failed", tab=ws["title"], error=repr(exc))
            await batch_service.add_log(
                batch_id, f"Tab “{ws['title']}” could not be read: {exc}",
                level="error", row_ref=ws["title"],
            )
            continue
        tab.headers_snapshot = headers  # best-effort; helps the mapping UI + drift
        # Per-tab mapping wins; else the source-level default; else auto-detect.
        mapping = (
            tab.column_mapping
            or (dict(source.column_mapping) if source.column_mapping else None)
            or import_parse.auto_map(headers)
        )
        # Tabs with no link/URL column at all (guidelines, keyword lists, stray
        # sheets) are AUTO-IGNORED — quietly, in green, and permanently (the
        # mapping UI can re-enable). They must never error a sync (owner rule).
        if not any(v == "source_page_url" for v in (mapping or {}).values()):
            tab.import_enabled = False
            await batch_service.add_log(
                batch_id,
                f"Tab “{ws['title']}” auto-ignored — it has no link/URL column "
                f"(looks like a notes/keywords tab). Re-enable it in the sheet "
                f"mapping if that's wrong.",
                level="info", row_ref=ws["title"],
            )
            done_tabs += 1
            await batch_service.update(batch_id, totals={"done_tabs": done_tabs})
            continue
        # Broken header cells ("#REF!", blanks) hide the USER column from
        # name-based mapping — every link then lands unassigned. Detect the
        # user column from the DATA instead (leftmost small-roster name column).
        mapping, inferred_user_col = import_parse.infer_user_column(mapping, headers, rows)
        if inferred_user_col:
            await batch_service.add_log(
                batch_id,
                f"Tab “{ws['title']}”: user column detected from its data "
                f"(header cell is “{inferred_user_col}”) — assignees will be filled.",
                level="info", row_ref=ws["title"],
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
            batch_id=batch_id,
        )
        db.add(imp)
        await db.flush()
        await import_service.stage_rows(
            db, imp, rows, default_link_type=(tab.link_type_name or ws["title"]),
            field_constants=(tab.field_constants or {}), default_target=default_target,
        )
        await db.commit()
        new_ids = await import_service.process(db, imp.id)
        refreshed = await db.get(Import, imp.id)
        all_new.extend(new_ids)
        tab_imported = refreshed.imported_rows if refreshed else len(new_ids)
        tab_new = len(new_ids)
        tab_existing = max(0, tab_imported - tab_new)
        total_rows += len(rows)
        total_imported += tab_imported
        total_failed += refreshed.error_rows if refreshed else 0
        # Skips are BENIGN (spacer rows / duplicates) — surfaced, never failures.
        total_skipped += (
            (refreshed.duplicate_rows or 0) + (refreshed.skipped_rows or 0)
        ) if refreshed else 0
        tab.row_count = len(rows)
        tab.last_synced_at = _now()
        source.last_sync_import_id = imp.id
        done_tabs += 1
        await batch_service.update(
            batch_id,
            totals={
                "done_tabs": done_tabs, "total": total_rows, "done": total_rows,
                "ok": total_imported, "failed": total_failed, "skipped": total_skipped,
            },
            counters_inc={"new_links": tab_new, "already_there": tab_existing},
        )
        # Honest per-tab accounting: NEW links vs rows that already existed
        # (those are just refreshed) — plus which links are actually new.
        await batch_service.add_log(
            batch_id,
            f"Tab “{ws['title']}”: {len(rows)} rows — "
            f"{tab_new} NEW link{'s' if tab_new != 1 else ''}, "
            f"{tab_existing} already there (refreshed), "
            f"{refreshed.error_rows if refreshed else 0} failed",
            level="warn" if (refreshed and refreshed.error_rows) else "info",
            row_ref=ws["title"],
            data={"import_id": str(imp.id), "new_links": tab_new},
        )
        if new_ids:
            from sqlalchemy import bindparam
            from sqlalchemy.dialects.postgresql import ARRAY as PG_ARRAY
            from sqlalchemy.dialects.postgresql import UUID as PG_UUID

            sample_stmt = text(
                "SELECT source_page_url FROM backlink_records WHERE id = ANY(:ids) LIMIT 10"
            ).bindparams(bindparam("ids", type_=PG_ARRAY(PG_UUID(as_uuid=True))))
            sample = (
                await db.execute(sample_stmt, {"ids": list(new_ids[:10])})
            ).scalars().all()
            more = f" (+{len(new_ids) - len(sample)} more)" if len(new_ids) > len(sample) else ""
            await batch_service.add_log(
                batch_id,
                f"New in “{ws['title']}”: " + ", ".join(sample) + more,
                row_ref=ws["title"],
            )

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

    # Duplicate accounting: how many duplicate-group memberships among this
    # sheet's links are NEW this run vs already known before it started.
    try:
        dup = (
            await db.execute(
                text(
                    "SELECT count(*) FILTER (WHERE m.created_at >= :t0) AS dup_new, "
                    "count(*) AS dup_total "
                    "FROM backlink_conflict_members m "
                    "JOIN backlink_records b ON b.id = m.backlink_id "
                    "WHERE b.source_sheet_id = :sid"
                ),
                {"t0": sync_started, "sid": source.id},
            )
        ).mappings().first() or {}
        dup_new = int(dup.get("dup_new", 0) or 0)
        dup_prev = max(0, int(dup.get("dup_total", 0) or 0) - dup_new)
        await batch_service.update(
            batch_id, counters_inc={"dup_new": dup_new, "dup_previous": dup_prev}
        )
        if dup_new:
            await batch_service.add_log(
                batch_id, f"{dup_new} NEW duplicate link(s) found in this sync "
                f"({dup_prev} were already known).", level="warn",
            )
    except Exception as exc:  # noqa: BLE001 — counters are best-effort
        log.warning("dup_counter_failed", error=repr(exc))

    await _auto_provision_users(db, source, batch_id)

    await batch_service.add_log(
        batch_id,
        f"Sync finished: {len(all_new)} NEW link{'s' if len(all_new) != 1 else ''} added, "
        f"{max(0, total_imported - len(all_new))} already existed (refreshed), "
        f"{total_failed} failed.",
    )
    if all_new and not settings.AUTO_QA_ON_IMPORT:
        await batch_service.add_log(
            batch_id,
            "New links are QA pending — start a check from the Backlinks list when ready "
            "(checks never start on their own).",
        )
    await batch_service.update(batch_id, meta={"current_step": "Finished"})
    await batch_service.finish(batch_id)

    return {
        "tabs": len(enabled),
        "rows": total_rows,
        "new": len(all_new),
        # Consumed by the worker ONLY when AUTO_QA_ON_IMPORT is on — the default
        # is manual QA, so new links wait as "QA pending".
        "new_ids": [str(i) for i in all_new],
        "batch_id": str(batch_id) if batch_id else None,
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

    # Which result columns to write — configurable per sheet (Mapping settings);
    # default = all of them.
    chosen = (source.writeback_columns or {}).get("columns") or list(_WRITEBACK_HEADERS)
    chosen = [c for c in _WRITEBACK_HEADERS if c in chosen]  # keep canonical order
    col_idx = [_WRITEBACK_HEADERS.index(c) for c in chosen]

    # Group rows by their sub-sheet/tab so each tab is written back to itself.
    by_tab: dict[str | None, dict[int, list]] = {}
    for bl in backlinks:
        try:
            sheet_row = int(bl.sheet_row_ref) + 1  # +1 for the header row
        except (TypeError, ValueError):
            continue
        status = bl.override_status or bl.status
        full = [
            status.value if status else "",
            bl.score if bl.score is not None else "",
            bl.index_status or "unchecked",
            bl.duplicate_status or "unique",
            bl.last_checked_at.strftime("%Y-%m-%d %H:%M") if bl.last_checked_at else "",
        ]
        by_tab.setdefault(bl.sheet_tab, {})[sheet_row] = [full[i] for i in col_idx]
    if not by_tab:
        return {"rows": 0}

    written = 0
    for tab, values_by_row in by_tab.items():
        if not values_by_row:
            continue
        try:
            await asyncio.to_thread(
                google_sheets.write_back,
                source.spreadsheet_id, tab, chosen, values_by_row,
            )
            written += 1
        except Exception as exc:  # noqa: BLE001 - write-back failure must not crash
            log.warning("writeback_failed", tab=tab, error=repr(exc))
    if written:
        # Write-back mutated the sheet — drop cached reads so the next sync/preview
        # sees the new column layout rather than a stale cached copy.
        await asyncio.to_thread(google_sheets.invalidate_sheet_cache, source.spreadsheet_id)
    source.last_sync_error = None
    await db.commit()
    return {"tabs_written": written}
