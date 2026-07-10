"""Competitor backlink ingest + gap analysis (Phase 8).

Ingest a competitor's link list (paste/CSV), canonicalise each URL with the SAME
identity system as our own backlinks, then roll up by registrable source domain and
compare against the project's own links: a competitor domain we don't link from is
a NEW_OPPORTUNITY; one we already use is EXISTING. Fully recomputed on each ingest
so the comparison is always consistent with current data.
"""

from __future__ import annotations

import uuid

from sqlalchemy import bindparam, delete, select, text
from sqlalchemy.dialects.postgresql import UUID as PGUUID
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.deps import AuthContext
from app.core.errors import NotFoundError, ValidationAppError
from app.crawler.normalize import normalize_url
from app.models.competitor import (
    CompetitorBacklink,
    CompetitorDomainDecision,
    CompetitorSheet,
    CompetitorSourceDomain,
)
from app.models.project import Project
from app.services import canonical_service


def competitor_key(sheet: CompetitorSheet) -> str:
    """Grouping identity for a parent competitor: the registrable domain of its
    URL (name as fallback for legacy rows without one)."""
    if sheet.competitor_url:
        parsed = normalize_url(sheet.competitor_url)
        if parsed.valid and parsed.registrable_domain:
            return parsed.registrable_domain
    return (sheet.name or "unknown").strip().lower()


async def _ensure_project(db: AsyncSession, ctx: AuthContext, project_id: uuid.UUID) -> None:
    """Validate the project belongs to the caller's workspace (assert_project is a
    no-op for unrestricted admins, so we must check ownership explicitly — mirrors
    project_settings_service._ensure_project)."""
    project = await db.get(Project, project_id)
    if project is None or project.workspace_id != ctx.workspace_id:
        raise NotFoundError("Project not found")
    ctx.assert_project(project_id)


# Header synonyms → parsed field. Covers SEMrush/Ahrefs backlink exports plus
# plain agency sheets. Compared after lower/strip.
_COMP_URL_HEADERS = {
    "source url", "url", "source_url", "backlink", "backlink url", "page url",
    "referring page url", "source page url", "referring page",
}
_COMP_HEADERS: dict[str, str] = {
    **{h: "url" for h in _COMP_URL_HEADERS},
    "anchor": "anchor", "anchor text": "anchor", "link anchor": "anchor",
    "rel": "rel", "follow": "rel", "link rel": "rel",
    "nofollow": "nofollow",  # SEMrush: TRUE/FALSE column
    "link type": "link_type", "type": "link_type", "seo task": "link_type",
}


def _split_line(line: str) -> list[str]:
    """Quote-aware split of one pasted line (tab wins over comma so URLs/anchors
    containing commas survive)."""
    import csv as _csv
    import io as _io

    delim = "\t" if "\t" in line else ","
    try:
        return [c.strip() for c in next(_csv.reader(_io.StringIO(line), delimiter=delim))]
    except (StopIteration, _csv.Error):
        return [line.strip()]


def parse_competitor_text(raw_text: str) -> dict:
    """Parse pasted text / a pasted CSV export → parsed rows + what was detected.

    Two modes:
    * header mode — the first line names its columns (SEMrush/Ahrefs exports or
      any sheet with a header row): columns are mapped by name, extra columns
      are ignored, missing optional columns don't block the import.
    * plain mode — positional ``url[, anchor[, rel[, link type]]]`` per line.
    Returns {format, mapping, rows: [(url, anchor, rel, link_type)], warnings}.
    """
    lines = [ln for ln in raw_text.splitlines() if ln.strip()]
    if not lines:
        return {"format": "plain", "mapping": {}, "rows": [], "warnings": []}

    first = [c.strip().strip('"').lower() for c in _split_line(lines[0])]
    header_hits = {i: _COMP_HEADERS[c] for i, c in enumerate(first) if c in _COMP_HEADERS}
    has_url_header = any(f == "url" for f in header_hits.values())

    rows: list[tuple[str, str | None, str | None, str | None]] = []
    warnings: list[str] = []

    def _clean_url(url: str) -> str | None:
        url = url.strip().strip('"')
        if not url:
            return None
        if not (url.startswith("http://") or url.startswith("https://")):
            url = "https://" + url
        return url

    if has_url_header:
        fmt = "semrush" if ("page ascore" in first or "domain ascore" in first) else "headers"
        idx: dict[str, int] = {}
        for i, field in header_hits.items():
            idx.setdefault(field, i)
        mapping = {first[i]: f for i, f in header_hits.items()}
        for line in lines[1:]:
            cells = _split_line(line)

            def cell(field: str) -> str | None:
                i = idx.get(field)
                return cells[i].strip().strip('"') if i is not None and i < len(cells) and cells[i].strip() else None

            url = _clean_url(cell("url") or "")
            if not url:
                warnings.append(f"Skipped row: source URL is missing ({line[:60]}…)")
                continue
            rel = cell("rel")
            if rel is None and "nofollow" in idx:
                flag = (cell("nofollow") or "").lower()
                rel = "nofollow" if flag in ("true", "1", "yes") else ("dofollow" if flag in ("false", "0", "no") else None)
            rows.append((url, cell("anchor"), rel, cell("link_type")))
        return {"format": fmt, "mapping": mapping, "rows": rows, "warnings": warnings[:20]}

    for line in lines:
        parts = _split_line(line)
        url = _clean_url(parts[0] if parts else "")
        if not url or parts[0].strip().strip('"').lower() in _COMP_URL_HEADERS:
            continue
        anchor = parts[1] if len(parts) > 1 and parts[1] else None
        rel = parts[2] if len(parts) > 2 and parts[2] else None
        link_type = parts[3] if len(parts) > 3 and parts[3] else None
        rows.append((url, anchor, rel, link_type))
    return {
        "format": "plain",
        "mapping": {"column 1": "url", "column 2": "anchor", "column 3": "rel", "column 4": "link_type"},
        "rows": rows,
        "warnings": warnings,
    }


def _parse_rows(raw_text: str) -> list[tuple[str, str | None, str | None, str | None]]:
    return parse_competitor_text(raw_text)["rows"]


async def ingest(
    db: AsyncSession,
    ctx: AuthContext,
    *,
    project_id: uuid.UUID,
    competitor_url: str,
    name: str,
    raw_text: str,
) -> CompetitorSheet:
    await _ensure_project(db, ctx, project_id)
    from app.services import batch_service

    comp = normalize_url(
        competitor_url if competitor_url.startswith(("http://", "https://")) else f"https://{competitor_url}"
    )
    if not comp.valid:
        raise ValidationAppError("Competitor URL is not a valid website address.")
    display_name = (name or "").strip()[:200] or (comp.registrable_domain or "Competitor")

    parsed = _parse_rows(raw_text)
    if not parsed:
        raise ValidationAppError("No competitor URLs found. Paste one source URL per line.")

    # Honest per-upload accounting: which of THESE links were already uploaded
    # for this project before (any previous sheet), by normalized URL.
    known_urls: set[str] = set()
    for (u,) in (
        await db.execute(
            select(CompetitorBacklink.raw_url).where(
                CompetitorBacklink.workspace_id == ctx.workspace_id,
                CompetitorBacklink.project_id == project_id,
            )
        )
    ).all():
        n = normalize_url(u)
        known_urls.add(n.normalized if n.valid else u)
    known_domains: set[str] = set(
        (
            await db.execute(
                select(CompetitorBacklink.source_domain).where(
                    CompetitorBacklink.workspace_id == ctx.workspace_id,
                    CompetitorBacklink.project_id == project_id,
                    CompetitorBacklink.source_domain.is_not(None),
                ).distinct()
            )
        ).scalars().all()
    )

    sheet = CompetitorSheet(
        workspace_id=ctx.workspace_id, project_id=project_id, name=display_name,
        competitor_url=(comp.normalized or competitor_url)[:500],
        source_kind="paste", status="ready", total_rows=len(parsed), created_by=ctx.user.id,
    )
    db.add(sheet)
    await db.flush()

    new_links = existing_links = 0
    upload_domains: set[str] = set()
    cache: dict[str, uuid.UUID] = {}
    for url, anchor, rel, link_type in parsed:
        parsed_url = normalize_url(url)
        domain = parsed_url.registrable_domain if parsed_url.valid else None
        norm = parsed_url.normalized if parsed_url.valid else url
        if norm in known_urls:
            existing_links += 1
        else:
            new_links += 1
            known_urls.add(norm)
        if domain:
            upload_domains.add(domain)
        canonical = await canonical_service.resolve_canonical(db, url, cache=cache)
        db.add(
            CompetitorBacklink(
                workspace_id=ctx.workspace_id, project_id=project_id, competitor_sheet_id=sheet.id,
                canonical_url_id=canonical.id if canonical else None,
                raw_url=url[:2048], source_domain=domain, anchor=anchor, rel=rel,
                link_type_label=(link_type or None) and str(link_type)[:120],
            )
        )
    await db.flush()

    # Per-UPLOAD numbers (what the owner sees on the row): domains first seen in
    # this upload vs domains this project already had competitor links from.
    sheet.new_domains = len(upload_domains - known_domains)
    sheet.existing_domains = len(upload_domains & known_domains)

    counts = await recompute_domains(db, ctx.workspace_id, project_id, sheet_id=sheet.id)
    sheet.domain_count = counts["domains"]
    await db.flush()

    # Stage the upload's domains as a competitor_import REVIEW batch so the Batch
    # Details view shows the domain list, supports DA/PA/AS/Spam checks, and can
    # approve the worthwhile ones into the Source Domains catalog (origin=competitor).
    # Fail-open: a staging hiccup never blocks the upload itself.
    from app.services import batch_review_service

    upload_log = (
        f"“{display_name}”: {len(parsed)} links pasted — {new_links} NEW, "
        f"{existing_links} already uploaded before, across {len(upload_domains)} domain(s) "
        f"({sheet.new_domains} domain(s) first seen in this upload). "
        f"Project now compares against {counts['new']} open opportunity domain(s)."
    )
    await batch_review_service.stage_competitor_domains(
        db, ctx, project_id=project_id, domains=list(upload_domains),
        label=f"Competitor upload — {display_name}", extra_log=upload_log,
    )
    return sheet


async def recompute_domains(
    db: AsyncSession, workspace_id: uuid.UUID, project_id: uuid.UUID, *, sheet_id: uuid.UUID | None = None
) -> dict:
    """Rebuild the per-domain comparison for a project from all its competitor links."""
    await db.execute(
        delete(CompetitorSourceDomain).where(
            CompetitorSourceDomain.workspace_id == workspace_id,
            CompetitorSourceDomain.project_id == project_id,
        )
    )
    await db.execute(
        text(
            """
            WITH comp AS (
                SELECT source_domain AS domain_key, count(*) AS url_count
                FROM competitor_backlinks
                WHERE workspace_id = :ws AND project_id = :pid AND source_domain IS NOT NULL
                GROUP BY source_domain
            ),
            ours AS (
                SELECT source_domain AS domain_key, count(*) AS cnt,
                       round(100.0 * count(*) FILTER (WHERE index_status = 'indexed')
                             / nullif(count(*), 0), 1) AS indexed_pct
                FROM backlink_records
                WHERE workspace_id = :ws AND project_id = :pid AND source_domain IS NOT NULL
                GROUP BY source_domain
            )
            INSERT INTO competitor_source_domains
                (id, workspace_id, project_id, competitor_sheet_id, domain_key, url_count,
                 category, our_link_count, our_indexed_pct, is_new, last_recomputed_at,
                 created_at, updated_at)
            SELECT gen_random_uuid(), :ws, :pid, :sheet, comp.domain_key, comp.url_count,
                   CASE WHEN coalesce(ours.cnt, 0) > 0 THEN 'existing' ELSE 'new_opportunity' END,
                   coalesce(ours.cnt, 0), ours.indexed_pct, (coalesce(ours.cnt, 0) = 0),
                   now(), now(), now()
            FROM comp LEFT JOIN ours USING (domain_key)
            """
        ),
        {"ws": workspace_id, "pid": project_id, "sheet": sheet_id},
    )
    await db.flush()

    row = (
        await db.execute(
            text(
                """
                SELECT count(*) AS domains,
                       count(*) FILTER (WHERE category = 'new_opportunity') AS new,
                       count(*) FILTER (WHERE category = 'existing') AS existing
                FROM competitor_source_domains WHERE workspace_id = :ws AND project_id = :pid
                """
            ),
            {"ws": workspace_id, "pid": project_id},
        )
    ).mappings().first() or {}
    return {"domains": row.get("domains", 0), "new": row.get("new", 0), "existing": row.get("existing", 0)}


async def delete_sheet(db: AsyncSession, ctx: AuthContext, sheet_id: uuid.UUID) -> str:
    """Delete one competitor upload and its links, then rebuild the domain
    comparison so opportunity counts stay truthful. Returns the sheet name."""
    sheet = await db.get(CompetitorSheet, sheet_id)
    if sheet is None or sheet.workspace_id != ctx.workspace_id:
        raise NotFoundError("Competitor upload not found")
    await _ensure_project(db, ctx, sheet.project_id)
    name, project_id = sheet.name, sheet.project_id
    await db.execute(
        delete(CompetitorBacklink).where(CompetitorBacklink.competitor_sheet_id == sheet_id)
    )
    await db.delete(sheet)
    await db.flush()
    await recompute_domains(db, ctx.workspace_id, project_id)
    return name


async def list_sheets(db: AsyncSession, ctx: AuthContext, project_id: uuid.UUID) -> list[CompetitorSheet]:
    await _ensure_project(db, ctx, project_id)
    return list(
        (
            await db.execute(
                select(CompetitorSheet)
                .where(CompetitorSheet.workspace_id == ctx.workspace_id, CompetitorSheet.project_id == project_id)
                .order_by(CompetitorSheet.created_at.desc())
            )
        ).scalars().all()
    )


# ── Opportunity workflow vocabulary (Phase 10 P2) ─────────────────────────────
# Statuses live in competitor_domain_decisions (the side-table that survives
# recompute). 'used' and 'duplicate' are DERIVED facts (the project actually has
# a backlink on the domain / the domain collapsed into another) — displayable
# but never manually set. The legacy pair open/dismissed stays valid so the
# existing dismiss/re-open flow keeps working unchanged.
OPPORTUNITY_STATUSES: tuple[str, ...] = (
    "new", "under_review", "validated", "approved", "rejected", "duplicate",
    "blocked", "needs_metrics", "needs_link_type_review", "ready", "assigned",
    "used", "archived",
)
_LEGACY_DECISION_STATUSES: tuple[str, ...] = ("open", "dismissed")
_DERIVED_ONLY_STATUSES: frozenset[str] = frozenset({"used", "duplicate"})
FILTERABLE_STATUSES: frozenset[str] = (
    frozenset(OPPORTUNITY_STATUSES) | frozenset(_LEGACY_DECISION_STATUSES)
)
SETTABLE_STATUSES: frozenset[str] = FILTERABLE_STATUSES - _DERIVED_ONLY_STATUSES


# Guest-post label variants: "Guest Post", "guestpost", "guest-post", "GP".
_GUEST_MATCH = r"(g.link_type_label ILIKE '%guest%' OR g.link_type_label ~* '^\s*gp\s*$')"
_GUEST_MATCH_CB = _GUEST_MATCH.replace("g.", "cb.")

# Whitelisted sort keys for the domain grid (never interpolate user input).
_DOMAIN_SORTS: dict[str, str] = {
    "domain": "d.domain_key",
    "links": "d.url_count",
    "ours": "d.our_link_count",
    "indexed": "d.our_indexed_pct",
    "da": "coalesce(d.da, sd.da)",
    "pa": "coalesce(d.pa, sd.pa)",
}


async def list_domains(
    db: AsyncSession,
    ctx: AuthContext,
    project_id: uuid.UUID,
    *,
    category: str | None = None,
    include_dismissed: bool = True,
    exclude_guest_posts: bool = False,
    search: str | None = None,
    status: str | None = None,
    sort: str | None = None,
    direction: str = "desc",
    limit: int = 500,
    offset: int = 0,
) -> list[dict]:
    """Domain rows + manual decision + guest-post tag. 'Used' is derived live
    (category = existing); manual dismissals survive recomputes via the
    decisions table. Searchable, sortable (whitelist) and paginated.
    ``status`` narrows on the workflow status (comma list, whitelisted;
    undecided rows read as 'open')."""
    await _ensure_project(db, ctx, project_id)
    conds = ["d.workspace_id = :ws", "d.project_id = :pid"]
    if category in ("existing", "new_opportunity"):
        conds.append("d.category = :cat")
    if not include_dismissed:
        conds.append("coalesce(dec.status, 'open') <> 'dismissed'")
    wanted_statuses: list[str] = []
    if status:
        wanted_statuses = [s.strip().lower() for s in status.split(",") if s.strip()]
        bad = sorted(set(wanted_statuses) - FILTERABLE_STATUSES)
        if bad:
            raise ValidationAppError(f"Unknown status filter value(s): {', '.join(bad)}")
        conds.append("coalesce(dec.status, 'open') IN :statuses")
    if exclude_guest_posts:
        conds.append(
            "NOT EXISTS (SELECT 1 FROM competitor_backlinks g WHERE g.project_id = d.project_id "
            f"AND g.source_domain = d.domain_key AND {_GUEST_MATCH})"
        )
    if search and search.strip():
        conds.append("d.domain_key ILIKE :q")
    order = "d.category ASC, d.url_count DESC"
    if sort in _DOMAIN_SORTS:
        dir_sql = "ASC" if direction == "asc" else "DESC"
        order = f"{_DOMAIN_SORTS[sort]} {dir_sql} NULLS LAST, d.domain_key ASC"
    sql = text(
        f"""
        SELECT d.id::text AS id, d.domain_key, d.url_count, d.category,
               d.our_link_count, d.our_indexed_pct, d.is_new,
               coalesce(d.da, sd.da) AS da, coalesce(d.pa, sd.pa) AS pa,
               coalesce(dec.status, 'open') AS decision,
               coalesce(dec.status, 'open') AS status,
               dec.reason AS decision_reason,
               dec.assigned_to::text AS assigned_to,
               EXISTS (
                 SELECT 1 FROM competitor_backlinks cb
                 WHERE cb.project_id = d.project_id AND cb.source_domain = d.domain_key
                   AND {_GUEST_MATCH_CB}
               ) AS has_guest_post
        FROM competitor_source_domains d
        LEFT JOIN competitor_domain_decisions dec
          ON dec.workspace_id = d.workspace_id AND dec.project_id = d.project_id
         AND dec.domain_key = d.domain_key
        LEFT JOIN source_domains sd
          ON sd.workspace_id = d.workspace_id AND sd.domain_key = d.domain_key
        WHERE {' AND '.join(conds)}
        ORDER BY {order}
        LIMIT :lim OFFSET :off
        """
    )
    params: dict = {
        "ws": ctx.workspace_id, "pid": project_id,
        "lim": max(1, min(limit, 2000)), "off": max(0, offset),
    }
    if category in ("existing", "new_opportunity"):
        params["cat"] = category
    if search and search.strip():
        params["q"] = f"%{search.strip()}%"
    if wanted_statuses:
        sql = sql.bindparams(bindparam("statuses", expanding=True))
        params["statuses"] = wanted_statuses
    rows = (await db.execute(sql, params)).mappings().all()
    return [dict(r) for r in rows]


async def sheet_backlinks(
    db: AsyncSession, ctx: AuthContext, sheet_id: uuid.UUID, *, limit: int = 1000
) -> list[dict]:
    """All links inside ONE competitor upload (parent = the competitor URL)."""
    sheet = await db.get(CompetitorSheet, sheet_id)
    if sheet is None or sheet.workspace_id != ctx.workspace_id:
        raise NotFoundError("Competitor upload not found")
    await _ensure_project(db, ctx, sheet.project_id)
    sql = text(
        """
        SELECT cb.raw_url AS url, cb.source_domain, cb.anchor, cb.rel,
               cb.link_type_label AS link_type,
               coalesce(d.da, sd.da) AS da, coalesce(d.pa, sd.pa) AS pa,
               sd.semrush_as AS semrush_as,
               d.category AS domain_category,
               coalesce(dec.status, 'open') AS decision
        FROM competitor_backlinks cb
        LEFT JOIN competitor_source_domains d
          ON d.workspace_id = cb.workspace_id AND d.project_id = cb.project_id
         AND d.domain_key = cb.source_domain
        LEFT JOIN source_domains sd
          ON sd.workspace_id = cb.workspace_id AND sd.domain_key = cb.source_domain
        LEFT JOIN competitor_domain_decisions dec
          ON dec.workspace_id = cb.workspace_id AND dec.project_id = cb.project_id
         AND dec.domain_key = cb.source_domain
        WHERE cb.competitor_sheet_id = :sid AND cb.workspace_id = :ws
        ORDER BY cb.source_domain ASC, cb.raw_url ASC
        LIMIT :lim
        """
    )
    rows = (
        await db.execute(
            sql, {"sid": sheet_id, "ws": ctx.workspace_id, "lim": max(1, min(limit, 5000))}
        )
    ).mappings().all()
    return [dict(r) for r in rows]


async def list_parents(
    db: AsyncSession, ctx: AuthContext, project_id: uuid.UUID
) -> list[dict]:
    """Roll uploads up to their parent competitor (grouped by competitor_key), so
    the desk shows one row per competitor with each upload folded underneath."""
    sheets = await list_sheets(db, ctx, project_id)
    groups: dict[str, list[CompetitorSheet]] = {}
    for sheet in sheets:
        groups.setdefault(competitor_key(sheet), []).append(sheet)

    out: list[dict] = []
    for key, group in groups.items():
        # list_sheets is newest-first, so the group preserves that order.
        display_name = next(
            (s.name for s in group if s.name and s.name.strip().lower() != key), key
        )
        competitor_url = next((s.competitor_url for s in group if s.competitor_url), None)
        created = [s.created_at for s in group if s.created_at]
        out.append(
            {
                "competitor": key,
                "display_name": display_name,
                "competitor_url": competitor_url,
                "uploads": len(group),
                "total_rows": sum(s.total_rows for s in group),
                "new_domains": sum(s.new_domains for s in group),
                "existing_domains": sum(s.existing_domains for s in group),
                "first_upload_at": min(created).isoformat() if created else None,
                "last_upload_at": max(created).isoformat() if created else None,
                "sheet_ids": [str(s.id) for s in group],
            }
        )
    out.sort(key=lambda g: g["total_rows"], reverse=True)
    return out


async def parent_backlinks(
    db: AsyncSession,
    ctx: AuthContext,
    project_id: uuid.UUID,
    *,
    competitor: str,
    q: str | None = None,
    limit: int = 1000,
) -> list[dict]:
    """All links across every upload belonging to one parent competitor (grouped
    by competitor_key) — the expand-under-parent view for the grouped desk."""
    sheets = await list_sheets(db, ctx, project_id)
    sids = [s.id for s in sheets if competitor_key(s) == competitor]
    if not sids:
        return []
    conds = ["cb.competitor_sheet_id IN :sids", "cb.workspace_id = :ws"]
    if q and q.strip():
        conds.append("(cb.raw_url ILIKE :q OR cb.source_domain ILIKE :q OR cb.anchor ILIKE :q)")
    sql = text(
        f"""
        SELECT cb.raw_url AS url, cb.source_domain, cb.anchor, cb.rel,
               cb.link_type_label AS link_type,
               cs.name AS upload_name, cs.created_at AS uploaded_at,
               coalesce(d.da, sd.da) AS da, coalesce(d.pa, sd.pa) AS pa,
               sd.semrush_as AS semrush_as,
               d.category AS domain_category,
               coalesce(dec.status, 'open') AS decision
        FROM competitor_backlinks cb
        JOIN competitor_sheets cs ON cs.id = cb.competitor_sheet_id
        LEFT JOIN competitor_source_domains d
          ON d.workspace_id = cb.workspace_id AND d.project_id = cb.project_id
         AND d.domain_key = cb.source_domain
        LEFT JOIN source_domains sd
          ON sd.workspace_id = cb.workspace_id AND sd.domain_key = cb.source_domain
        LEFT JOIN competitor_domain_decisions dec
          ON dec.workspace_id = cb.workspace_id AND dec.project_id = cb.project_id
         AND dec.domain_key = cb.source_domain
        WHERE {' AND '.join(conds)}
        ORDER BY cb.source_domain ASC, cb.raw_url ASC
        LIMIT :lim
        """
    ).bindparams(bindparam("sids", expanding=True))
    params: dict = {"sids": sids, "ws": ctx.workspace_id, "lim": max(1, min(limit, 5000))}
    if q and q.strip():
        params["q"] = f"%{q.strip()}%"
    rows = (await db.execute(sql, params)).mappings().all()
    out: list[dict] = []
    for r in rows:
        d = dict(r)
        if d.get("uploaded_at") is not None:
            d["uploaded_at"] = str(d["uploaded_at"])
        out.append(d)
    return out


async def domain_backlinks(
    db: AsyncSession, ctx: AuthContext, project_id: uuid.UUID, domain: str, *, limit: int = 300
) -> list[dict]:
    """The competitor links behind one domain row (for the expand-in-place view)."""
    await _ensure_project(db, ctx, project_id)
    rows = (
        await db.execute(
            select(
                CompetitorBacklink.raw_url,
                CompetitorBacklink.anchor,
                CompetitorBacklink.rel,
                CompetitorBacklink.link_type_label,
                CompetitorSheet.name,
                CompetitorSheet.competitor_url,
            )
            .join(CompetitorSheet, CompetitorSheet.id == CompetitorBacklink.competitor_sheet_id)
            .where(
                CompetitorBacklink.workspace_id == ctx.workspace_id,
                CompetitorBacklink.project_id == project_id,
                CompetitorBacklink.source_domain == domain.lower().strip()[:255],
            )
            .order_by(CompetitorBacklink.raw_url.asc())
            .limit(max(1, min(limit, 1000)))
        )
    ).all()
    return [
        {
            "url": u, "anchor": a, "rel": r, "link_type": lt,
            "upload_name": sn, "competitor_url": cu,
        }
        for u, a, r, lt, sn, cu in rows
    ]


async def decide(
    db: AsyncSession,
    ctx: AuthContext,
    project_id: uuid.UUID,
    domain_key: str,
    *,
    status: str,
    reason: str | None = None,
) -> None:
    """Record a manual opportunity decision: 'dismissed' hides it from the active
    list; 'open' re-opens it. Upsert so recomputes never lose it."""
    from datetime import datetime, timezone

    from sqlalchemy.dialects.postgresql import insert as pg_insert

    await _ensure_project(db, ctx, project_id)
    if status not in ("dismissed", "open"):
        raise ValidationAppError("Decision must be 'dismissed' or 'open'.")
    stmt = (
        pg_insert(CompetitorDomainDecision)
        .values(
            workspace_id=ctx.workspace_id, project_id=project_id,
            domain_key=domain_key.lower()[:255], status=status,
            reason=(reason or "")[:300] or None, decided_by=ctx.user.id,
            decided_at=datetime.now(timezone.utc),
        )
        .on_conflict_do_update(
            constraint="uq_comp_domain_decision",
            set_={
                "status": status,
                "reason": (reason or "")[:300] or None,
                "decided_by": ctx.user.id,
                "decided_at": datetime.now(timezone.utc),
            },
        )
    )
    await db.execute(stmt)
    await db.flush()


def validate_settable_status(status: str) -> str:
    """Normalize + validate a manually-set workflow status. Pure (no DB) so the
    transition rule is unit-testable: 'used'/'duplicate' are derived-only and
    always rejected; anything outside the vocabulary is rejected."""
    status = (status or "").strip().lower()
    if status in _DERIVED_ONLY_STATUSES:
        raise ValidationAppError(
            f"'{status}' is derived automatically and cannot be set manually."
        )
    if status not in SETTABLE_STATUSES:
        raise ValidationAppError(
            "Unknown status. Allowed: " + ", ".join(sorted(SETTABLE_STATUSES))
        )
    return status


async def set_domain_status(
    db: AsyncSession,
    ctx: AuthContext,
    project_id: uuid.UUID,
    domain: str,
    *,
    status: str,
    note: str | None = None,
    assigned_to: uuid.UUID | None = None,
) -> dict:
    """Set the workflow status for one competitor domain (Phase 10 P2). Upserts
    the decisions side-table so recomputes never lose it — same durability as
    dismiss/re-open, which stays on :func:`decide` unchanged. ``note`` lands in
    the existing ``reason`` column; ``assigned_to`` is the user working it.
    The router gates who may call this (Manager+)."""
    from datetime import datetime, timezone

    from sqlalchemy.dialects.postgresql import insert as pg_insert

    # Validate BEFORE any DB access so the rule is enforced no matter the caller.
    status = validate_settable_status(status)
    await _ensure_project(db, ctx, project_id)
    now = datetime.now(timezone.utc)
    reason = (note or "").strip()[:300] or None
    stmt = (
        pg_insert(CompetitorDomainDecision)
        .values(
            workspace_id=ctx.workspace_id, project_id=project_id,
            domain_key=domain.lower().strip()[:255], status=status,
            reason=reason, assigned_to=assigned_to,
            decided_by=ctx.user.id, decided_at=now,
        )
        .on_conflict_do_update(
            constraint="uq_comp_domain_decision",
            set_={
                "status": status,
                "reason": reason,
                "assigned_to": assigned_to,
                "decided_by": ctx.user.id,
                "decided_at": now,
            },
        )
    )
    await db.execute(stmt)
    await db.flush()
    return {
        "domain_key": domain.lower().strip()[:255],
        "status": status,
        "note": reason,
        "assigned_to": str(assigned_to) if assigned_to else None,
    }


async def check_metrics(
    db: AsyncSession, ctx: AuthContext, project_id: uuid.UUID,
    *, freshness_days: int = 10, limit: int = 100, force: bool = False,
) -> dict:
    """Fill DA/PA for this project's competitor domains, REUSE-FIRST:
    1. copy from ``source_domains`` when we already checked that domain recently
       (zero API cost); 2. skip domains checked within the freshness window;
    3. only then call the metrics API. Every step is recorded (batch + history)."""
    import httpx as _httpx
    from datetime import datetime, timedelta, timezone

    from app.integrations import domain_metrics as dm_integration
    from app.models.metric_history import MetricCheckHistory
    from app.services import batch_service

    await _ensure_project(db, ctx, project_id)
    cutoff = datetime.now(timezone.utc) - timedelta(days=max(1, freshness_days))

    rows = (
        await db.execute(
            select(CompetitorSourceDomain)
            .where(
                CompetitorSourceDomain.workspace_id == ctx.workspace_id,
                CompetitorSourceDomain.project_id == project_id,
            )
            .order_by(CompetitorSourceDomain.da.is_(None).desc(), CompetitorSourceDomain.url_count.desc())
            .limit(max(1, min(limit, 500)))
        )
    ).scalars().all()
    if not rows:
        return {"checked": 0, "from_cache": 0, "api_calls": 0, "skipped_fresh": 0}

    batch_id = await batch_service.start(
        "competitor_check", ctx.workspace_id, project_id=project_id,
        label=f"Competitor metrics check ({len(rows)} domains)", started_by=ctx.user.id,
        total=len(rows),
    )

    # Our own source-domain metrics (already paid for) → free reuse.
    from sqlalchemy import String as _String
    from sqlalchemy import bindparam as _bindparam
    from sqlalchemy.dialects.postgresql import ARRAY as _ARRAY

    sd_stmt = text(
        "SELECT domain_key, da, pa, metrics_updated_at FROM source_domains "
        "WHERE workspace_id = :ws AND domain_key = ANY(:keys)"
    ).bindparams(_bindparam("keys", type_=_ARRAY(_String())))
    sd_map = {
        r["domain_key"]: r
        for r in (
            await db.execute(sd_stmt, {"ws": ctx.workspace_id, "keys": [r.domain_key for r in rows]})
        ).mappings().all()
    }

    checked = cached = api_calls = skipped = 0
    async with _httpx.AsyncClient(timeout=20) as client:
        for row in rows:
            if not force and row.da is not None and row.updated_at and row.updated_at >= cutoff:
                skipped += 1
                continue
            sd = sd_map.get(row.domain_key)
            if (
                not force and sd and sd["da"] is not None
                and sd["metrics_updated_at"] and sd["metrics_updated_at"] >= cutoff
            ):
                row.da = sd["da"]
                row.pa = sd["pa"]
                cached += 1
                checked += 1
                db.add(MetricCheckHistory(
                    workspace_id=ctx.workspace_id, entity_kind="domain",
                    entity_key=row.domain_key[:600], provider="moz", from_cache=True,
                    ok=True, batch_id=batch_id,
                ))
                continue
            try:
                data = await dm_integration.fetch_all(row.domain_key, client)
            except Exception:  # noqa: BLE001 — one bad domain must not stop the run
                data = {}
            if data.get("da") is not None:
                row.da = data.get("da")
                row.pa = data.get("pa")
            api_calls += 1
            checked += 1
            db.add(MetricCheckHistory(
                workspace_id=ctx.workspace_id, entity_kind="domain",
                entity_key=row.domain_key[:600], provider="moz", from_cache=False,
                ok=bool(data), batch_id=batch_id,
            ))
    await db.flush()

    await batch_service.update(
        batch_id,
        totals={"total": len(rows), "done": len(rows), "ok": checked, "skipped": skipped},
        counters_inc={"api_calls": api_calls, "api_cached": cached},
    )
    await batch_service.add_log(
        batch_id,
        f"{checked} domain(s) updated — {cached} reused from our own recent checks (no API cost), "
        f"{api_calls} fresh API call(s), {skipped} already fresh (checked within {freshness_days} days).",
    )
    await batch_service.finish(batch_id)
    return {"checked": checked, "from_cache": cached, "api_calls": api_calls, "skipped_fresh": skipped}


async def summary(db: AsyncSession, ctx: AuthContext, project_id: uuid.UUID) -> dict:
    await _ensure_project(db, ctx, project_id)
    row = (
        await db.execute(
            text(
                """
                SELECT count(*) AS domains,
                       count(*) FILTER (
                           WHERE d.category = 'new_opportunity'
                             AND coalesce(dec.status, 'open') <> 'dismissed'
                       ) AS new_opportunities,
                       count(*) FILTER (WHERE d.category = 'existing') AS existing,
                       count(*) FILTER (WHERE coalesce(dec.status, 'open') = 'dismissed') AS dismissed,
                       coalesce(sum(d.url_count), 0) AS competitor_links,
                       round(avg(coalesce(d.da, sd.da))
                             FILTER (WHERE coalesce(d.da, sd.da) IS NOT NULL))::int AS avg_da,
                       round(avg(sd.semrush_as)
                             FILTER (WHERE sd.semrush_as IS NOT NULL))::int AS avg_as
                FROM competitor_source_domains d
                LEFT JOIN competitor_domain_decisions dec
                  ON dec.workspace_id = d.workspace_id AND dec.project_id = d.project_id
                 AND dec.domain_key = d.domain_key
                LEFT JOIN source_domains sd
                  ON sd.workspace_id = d.workspace_id AND sd.domain_key = d.domain_key
                WHERE d.workspace_id = :ws AND d.project_id = :pid
                """
            ),
            {"ws": ctx.workspace_id, "pid": project_id},
        )
    ).mappings().first() or {}
    return dict(row)
