"""Backlink read/grid/detail/override logic.

The grid uses **keyset** pagination on an indexed ``(sort_col, id)`` pair so paging
stays constant-time at 1M+ rows. Tenant isolation (``workspace_id``) and project
scoping are injected into every query.
"""

from __future__ import annotations

import uuid
from datetime import date, datetime, time, timedelta, timezone

from sqlalchemy import Select, and_, exists, func, or_, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.cursor import decode_cursor, encode_cursor
from app.core.deps import AuthContext
from app.core.errors import NotFoundError, PermissionDeniedError
from app.crawler.normalize import normalize_url, registrable_domain
from app.models.backlink import BacklinkRecord
from app.models.crawl import BacklinkHistory, BacklinkIssue, CrawlResult
from app.models.enums import HistoryEventType, OverallStatus, RelType
from app.models.source_domain import SourceDomain
from app.schemas.backlink import BacklinkCreate, BacklinkFilters, BacklinkUpdate

_EPOCH = datetime(1970, 1, 1, tzinfo=timezone.utc)

# Date-range filter keys → column. ``placement``/``sheet`` are Date columns
# (inclusive both ends via >= from / <= to); the rest are TIMESTAMPTZ (>= from /
# < to+1day so the end date is inclusive of the whole day). Bounds are built as
# real Python date/datetime objects — never text casts (asyncpg rejects strings).
_DATE_COLS = {
    "placement": BacklinkRecord.placement_date,
    "discovered": BacklinkRecord.discovered_at,
    "qa": BacklinkRecord.last_checked_at,
    "completed": BacklinkRecord.qa_completed_at,
    "imported": BacklinkRecord.created_at,
    "sheet": BacklinkRecord.sheet_created_date,
    "assigned": BacklinkRecord.assigned_at,
    "updated": BacklinkRecord.updated_at,
}
# Date-typed columns use an inclusive <= upper bound; TIMESTAMPTZ use < to+1day.
_DATE_TYPE_KEYS = {"placement", "sheet"}


def _scope(stmt: Select, ctx: AuthContext) -> Select:
    stmt = stmt.where(BacklinkRecord.workspace_id == ctx.workspace_id)
    if ctx.allowed_project_ids is not None:
        stmt = stmt.where(BacklinkRecord.project_id.in_(ctx.allowed_project_ids or {uuid.uuid4()}))
    return stmt


_BLANKS = "(blanks)"


def _csv(value) -> list[str]:
    """Split a single-or-comma-separated filter value into clean parts."""
    return [p.strip() for p in str(value).split(",") if p.strip()]


def _multi_clause(column, value, *, valid: set[str] | None = None, lower: bool = False):
    """Build a WHERE clause for a multi-select value: ``IN (...)`` over the valid
    parts, with the ``(blanks)`` sentinel matching NULL/empty. Returns None when
    nothing valid remains (filter is skipped, never errors)."""
    parts = _csv(value)
    want_blanks = any(p.lower() == _BLANKS for p in parts)
    vals = [p.lower() if lower else p for p in parts if p.lower() != _BLANKS]
    if valid is not None:
        vals = [v for v in vals if v in valid]
    conds = []
    if vals:
        conds.append(column.in_(vals))
    if want_blanks:
        # NULL, empty, or whitespace-only all count as "blank" (matches the
        # dashboard KPI's btrim grouping so counts and drill-downs agree).
        conds.append(or_(column.is_(None), func.btrim(column) == ""))
    if not conds:
        return None
    return or_(*conds) if len(conds) > 1 else conds[0]


def _apply_filters(stmt: Select, f: BacklinkFilters) -> Select:
    if f.project_id:
        stmt = stmt.where(BacklinkRecord.project_id == f.project_id)
    if f.status:
        eff = func.coalesce(BacklinkRecord.override_status, BacklinkRecord.status)
        vals = [OverallStatus(s) for s in _csv(f.status) if s in OverallStatus._value2member_map_]
        if vals:
            stmt = stmt.where(eff.in_(vals))
    if f.score_min is not None:
        stmt = stmt.where(BacklinkRecord.score >= f.score_min)
    if f.score_max is not None:
        stmt = stmt.where(BacklinkRecord.score <= f.score_max)
    if f.rel:
        vals = [RelType(r) for r in _csv(f.rel) if r in RelType._value2member_map_]
        if vals:
            stmt = stmt.where(BacklinkRecord.current_rel.in_(vals))
    if f.indexability:
        stmt = stmt.where(BacklinkRecord.indexability == f.indexability)
    if f.robots_status:
        stmt = stmt.where(BacklinkRecord.robots_status == f.robots_status)
    if f.canonical_status:
        # Multi-value (comma list), so the dashboard "Canonical issue" card
        # (mismatch,cross_domain) drills to the exact same rows it counted.
        clause = _multi_clause(BacklinkRecord.canonical_status, f.canonical_status)
        if clause is not None:
            stmt = stmt.where(clause)
    if f.vendor_id:
        stmt = stmt.where(BacklinkRecord.vendor_id == f.vendor_id)
    if f.campaign_id:
        stmt = stmt.where(BacklinkRecord.campaign_id == f.campaign_id)
    if f.assigned_user_id:
        stmt = stmt.where(BacklinkRecord.assigned_user_id == f.assigned_user_id)
    if f.assigned_user_label:
        clause = _multi_clause(BacklinkRecord.assigned_user_label, f.assigned_user_label)
        if clause is not None:
            stmt = stmt.where(clause)
    if f.link_type:
        clause = _multi_clause(BacklinkRecord.link_type, f.link_type)
        if clause is not None:
            stmt = stmt.where(clause)
    if f.duplicate_status:
        conds = []
        for part in _csv(f.duplicate_status):
            if part == "duplicate":  # any duplicate
                conds.append(BacklinkRecord.is_duplicate.is_(True))
            elif part == "unique":
                conds.append(BacklinkRecord.is_duplicate.is_not(True))
            else:
                conds.append(BacklinkRecord.duplicate_status == part)
        if conds:
            stmt = stmt.where(or_(*conds) if len(conds) > 1 else conds[0])
    if f.index_status:
        conds = []
        for part in _csv(f.index_status):
            if part == "unchecked":
                conds.append(BacklinkRecord.index_status.is_(None))
            else:
                conds.append(BacklinkRecord.index_status == part)
        if conds:
            stmt = stmt.where(or_(*conds) if len(conds) > 1 else conds[0])
    if f.http_status:
        # Exact status or comma-list ("200,301"); non-numeric parts are ignored.
        codes = [int(p) for p in _csv(f.http_status) if p.isdigit()]
        if codes:
            stmt = stmt.where(BacklinkRecord.http_status.in_(codes))
    if f.broken:
        stmt = stmt.where(BacklinkRecord.http_status >= 400)
    if f.http_class:
        # "4xx" and/or "5xx" — individually selectable client errors vs server errors.
        ranges = []
        parts = {p.strip().lower() for p in _csv(f.http_class)}
        if "4xx" in parts:
            ranges.append(and_(BacklinkRecord.http_status >= 400, BacklinkRecord.http_status < 500))
        if "5xx" in parts:
            ranges.append(BacklinkRecord.http_status >= 500)
        if ranges:
            stmt = stmt.where(or_(*ranges) if len(ranges) > 1 else ranges[0])
    if f.link_missing:
        # link_found IS FALSE — identical to the analytics "Missing" metric.
        stmt = stmt.where(BacklinkRecord.link_found.is_(False))
    if f.no_placement:
        # Links with no placement date — the set the "Fill missing dates" and
        # per-row date editor act on.
        stmt = stmt.where(BacklinkRecord.placement_date.is_(None))
    if f.no_user:
        # No owner assigned — blank/NULL label (same set as the (blanks) chip).
        stmt = stmt.where(
            or_(
                BacklinkRecord.assigned_user_label.is_(None),
                func.trim(BacklinkRecord.assigned_user_label) == "",
            )
        )
    # spam_min / da_min / pa_min / as_min / orphaned resolve against the
    # source_domains aggregate row. source_domains is unique per
    # (workspace_id, domain_key) so the LEFT JOIN never fans out the backlink
    # rows (keyset/sort stay intact). Join once, share the same vocabulary as
    # analytics so a KPI/analytics filter and this list always agree.
    if (
        f.spam_min is not None or f.orphaned
        or f.da_min is not None or f.pa_min is not None or f.as_min is not None
    ):
        stmt = stmt.outerjoin(
            SourceDomain,
            and_(
                SourceDomain.workspace_id == BacklinkRecord.workspace_id,
                SourceDomain.domain_key == BacklinkRecord.source_domain,
            ),
        )
        if f.spam_min is not None:
            stmt = stmt.where(SourceDomain.spam_score >= f.spam_min)
        if f.da_min is not None:
            stmt = stmt.where(SourceDomain.da >= f.da_min)
        if f.pa_min is not None:
            stmt = stmt.where(SourceDomain.pa >= f.pa_min)
        if f.as_min is not None:
            stmt = stmt.where(SourceDomain.semrush_as >= f.as_min)
        if f.orphaned:
            # orphaned = the source domain has no source_domains aggregate row.
            stmt = stmt.where(SourceDomain.id.is_(None))
    if f.source_domain:
        clause = _multi_clause(BacklinkRecord.source_domain, f.source_domain, lower=True)
        if clause is not None:
            stmt = stmt.where(clause)
    if f.tag:
        stmt = stmt.where(BacklinkRecord.tags.any(f.tag))
    if f.search:
        like = f"%{f.search.strip()}%"
        stmt = stmt.where(
            or_(
                BacklinkRecord.source_page_url.ilike(like),
                BacklinkRecord.target_url.ilike(like),
                BacklinkRecord.current_anchor_text.ilike(like),
            )
        )
    if f.target:
        tlike = f"%{f.target.strip()}%"
        stmt = stmt.where(
            or_(
                BacklinkRecord.target_url.ilike(tlike),
                BacklinkRecord.expected_target_url.ilike(tlike),
            )
        )
    if f.issue_label:
        stmt = stmt.where(
            exists().where(
                and_(
                    BacklinkIssue.backlink_id == BacklinkRecord.id,
                    BacklinkIssue.label == f.issue_label,
                )
            )
        )
    for key, col in _DATE_COLS.items():
        d_from = getattr(f, f"{key}_from", None)
        d_to = getattr(f, f"{key}_to", None)
        is_date_col = key in _DATE_TYPE_KEYS
        if d_from is not None:
            lo = d_from if is_date_col else datetime.combine(d_from, time.min, tzinfo=timezone.utc)
            stmt = stmt.where(col >= lo)
        if d_to is not None:
            if is_date_col:
                stmt = stmt.where(col <= d_to)  # Date column: inclusive end date
            else:
                # TIMESTAMPTZ: < start of the next day → inclusive of the whole end day.
                hi = datetime.combine(d_to + timedelta(days=1), time.min, tzinfo=timezone.utc)
                stmt = stmt.where(col < hi)
    return stmt


async def delete_backlink(db: AsyncSession, ctx: AuthContext, backlink_id: uuid.UUID) -> str:
    """Delete one backlink plus its live issue rows and duplicate-group
    membership (groups left with fewer than 2 links are removed too). Crawl
    history stays as immutable audit. Returns the deleted source URL."""
    from sqlalchemy import delete as sa_delete

    from app.models.conflict import BacklinkConflict, BacklinkConflictMember

    bl = await db.get(BacklinkRecord, backlink_id)
    if bl is None or bl.workspace_id != ctx.workspace_id:
        raise NotFoundError("Backlink not found")
    ctx.assert_project(bl.project_id)
    source_url = bl.source_page_url

    # Tombstone BEFORE the delete — backlink_history has no FK to
    # backlink_records, so the event outlives the row (retention-grade audit).
    from app.services import history_service

    await history_service.record_link_event(
        db, backlink=bl, event_type=HistoryEventType.DELETED,
        old_value=source_url, actor_user_id=ctx.user.id, actor_role=ctx.role.value,
        source="ui",
    )

    await db.execute(sa_delete(BacklinkIssue).where(BacklinkIssue.backlink_id == backlink_id))
    conflict_ids = list(
        (
            await db.execute(
                select(BacklinkConflictMember.conflict_id).where(
                    BacklinkConflictMember.backlink_id == backlink_id
                )
            )
        ).scalars().all()
    )
    await db.execute(
        sa_delete(BacklinkConflictMember).where(BacklinkConflictMember.backlink_id == backlink_id)
    )
    for cid in conflict_ids:
        remaining = (
            await db.execute(
                select(func.count())
                .select_from(BacklinkConflictMember)
                .where(BacklinkConflictMember.conflict_id == cid)
            )
        ).scalar_one()
        if remaining < 2:  # a "duplicate group" of one is no duplicate at all
            await db.execute(
                sa_delete(BacklinkConflictMember).where(BacklinkConflictMember.conflict_id == cid)
            )
            await db.execute(sa_delete(BacklinkConflict).where(BacklinkConflict.id == cid))
    await db.delete(bl)
    await db.flush()
    return source_url


# Nullable datetime sort keys → column; NULLs coalesce to _EPOCH so keyset
# ordering + cursor comparison stay total. ``placement_date`` is a Date column
# (coalesced to _EPOCH's date); the rest are TIMESTAMPTZ.
_DATETIME_SORTS = {
    "last_checked_at": BacklinkRecord.last_checked_at,
    "discovered_at": BacklinkRecord.discovered_at,
    "qa_completed_at": BacklinkRecord.qa_completed_at,
    "assigned_at": BacklinkRecord.assigned_at,
    "updated_at": BacklinkRecord.updated_at,
}
_EPOCH_DATE = _EPOCH.date()


def _sort_column(sort: str):
    if sort in _DATETIME_SORTS:
        return func.coalesce(_DATETIME_SORTS[sort], _EPOCH)
    if sort == "placement_date":
        return func.coalesce(BacklinkRecord.placement_date, _EPOCH_DATE)
    if sort == "created_at":
        return BacklinkRecord.created_at
    if sort == "source_domain":
        return func.coalesce(BacklinkRecord.source_domain, "")
    if sort == "link_type":
        return func.coalesce(BacklinkRecord.link_type, "")
    if sort == "http_status":
        return func.coalesce(BacklinkRecord.http_status, -1)
    return func.coalesce(BacklinkRecord.score, -1)  # default: score


def _parse_cursor_value(sort: str, raw: str):
    if sort in _DATETIME_SORTS or sort == "created_at":
        return datetime.fromisoformat(raw)
    if sort == "placement_date":
        return date.fromisoformat(raw)
    if sort in ("source_domain", "link_type"):
        return raw
    return int(raw)


def _cursor_sort_value(sort: str, last: BacklinkRecord) -> object:
    if sort == "score":
        return last.score if last.score is not None else -1
    if sort in _DATETIME_SORTS:
        return (getattr(last, sort) or _EPOCH).isoformat()
    if sort == "placement_date":
        return (last.placement_date or _EPOCH_DATE).isoformat()
    if sort == "created_at":
        return last.created_at.isoformat()
    if sort == "source_domain":
        return last.source_domain or ""
    if sort == "link_type":
        return last.link_type or ""
    if sort == "http_status":
        return last.http_status if last.http_status is not None else -1
    return last.created_at.isoformat()


async def list_backlinks(
    db: AsyncSession,
    ctx: AuthContext,
    filters: BacklinkFilters,
    *,
    sort: str = "score",
    direction: str = "desc",
    limit: int = 50,
    cursor: str | None = None,
) -> tuple[list[BacklinkRecord], str | None, bool]:
    limit = max(1, min(limit, 200))
    sort_col = _sort_column(sort)
    asc = direction == "asc"

    stmt = _apply_filters(_scope(select(BacklinkRecord), ctx), filters)

    if cursor:
        raw_value, last_id = decode_cursor(cursor)
        value = _parse_cursor_value(sort, raw_value)
        # Keyset: (sort, id) strictly beyond the cursor tuple in scan direction.
        if asc:
            stmt = stmt.where(
                or_(sort_col > value, and_(sort_col == value, BacklinkRecord.id > last_id))
            )
        else:
            stmt = stmt.where(
                or_(sort_col < value, and_(sort_col == value, BacklinkRecord.id < last_id))
            )

    order = (sort_col.asc(), BacklinkRecord.id.asc()) if asc else (sort_col.desc(), BacklinkRecord.id.desc())
    stmt = stmt.order_by(*order).limit(limit + 1)
    rows = list((await db.execute(stmt)).scalars().all())

    has_more = len(rows) > limit
    rows = rows[:limit]
    next_cursor = None
    if has_more and rows:
        last = rows[-1]
        next_cursor = encode_cursor(_cursor_sort_value(sort, last), last.id)
    return rows, next_cursor, has_more


async def targets_per_source(
    db: AsyncSession, rows: list[BacklinkRecord]
) -> dict[uuid.UUID, int]:
    """For the rows on screen: how many DIFFERENT target URLs the same source
    page links to within its project (bounded — one grouped query per page)."""
    if not rows:
        return {}
    pairs = {(r.project_id, r.source_url_normalized) for r in rows}
    conds = [
        and_(
            BacklinkRecord.project_id == pid,
            BacklinkRecord.source_url_normalized == norm,
        )
        for pid, norm in pairs
    ]
    result = await db.execute(
        select(
            BacklinkRecord.project_id,
            BacklinkRecord.source_url_normalized,
            func.count(func.distinct(BacklinkRecord.target_url_normalized)),
        )
        .where(or_(*conds))
        .group_by(BacklinkRecord.project_id, BacklinkRecord.source_url_normalized)
    )
    counts = {(pid, norm): int(n) for pid, norm, n in result.all()}
    return {r.id: counts.get((r.project_id, r.source_url_normalized), 1) for r in rows}


async def domain_metrics_per_row(
    db: AsyncSession, rows: list[BacklinkRecord]
) -> dict[uuid.UUID, tuple[int | None, int | None, int | None]]:
    """For the rows on screen: the source domain's Moz DA/PA + Semrush AS from
    the stored ``source_domains`` aggregates (unique per workspace+domain, so
    one bounded IN query per page — no join on the keyset hot path)."""
    if not rows:
        return {}
    domains = {r.source_domain for r in rows if r.source_domain}
    if not domains:
        return {}
    result = await db.execute(
        select(
            SourceDomain.workspace_id, SourceDomain.domain_key,
            SourceDomain.da, SourceDomain.pa, SourceDomain.semrush_as, SourceDomain.spam_score,
        ).where(
            SourceDomain.workspace_id.in_({r.workspace_id for r in rows}),
            SourceDomain.domain_key.in_(domains),
        )
    )
    metrics = {(ws, key): (da, pa, sas, spam) for ws, key, da, pa, sas, spam in result.all()}
    return {
        r.id: metrics[(r.workspace_id, r.source_domain)]
        for r in rows
        if (r.workspace_id, r.source_domain) in metrics
    }


async def count_backlinks(db: AsyncSession, ctx: AuthContext, filters: BacklinkFilters) -> int:
    stmt = _apply_filters(_scope(select(func.count(BacklinkRecord.id)), ctx), filters)
    return int((await db.execute(stmt)).scalar_one())


_EXPORT_HEADERS = [
    "Source URL", "Target URL", "Source domain", "Status", "Score", "Index status",
    "Rel", "HTTP", "Link found", "Duplicate", "Link type", "Assigned user",
    "DA", "PA", "AS", "Spam", "Placement date", "Discovered", "QA completed", "Created",
]
# Cap to protect memory; the frontend/logs surface truncation honestly.
EXPORT_ROW_CAP = 50_000


async def export_rows(
    db: AsyncSession, ctx: AuthContext, filters: BacklinkFilters, *,
    sort: str, direction: str, cap: int = EXPORT_ROW_CAP,
) -> tuple[list[str], list[list], bool]:
    """The FULL filtered backlink set for a server-side export (not the 200-row
    page cap): keyset-paged internally, domain metrics enriched per page. Returns
    (headers, rows, truncated)."""
    def _v(x):
        return getattr(x, "value", x)

    rows_out: list[list] = []
    cursor: str | None = None
    truncated = False
    while True:
        page, cursor, has_more = await list_backlinks(
            db, ctx, filters, sort=sort, direction=direction, limit=200, cursor=cursor
        )
        dm = await domain_metrics_per_row(db, page)
        for r in page:
            da, pa, sas, spam = dm.get(r.id, (None, None, None, None))
            rows_out.append([
                r.source_page_url, r.target_url, r.source_domain,
                _v(r.override_status or r.status), r.score, _v(r.index_status),
                _v(r.current_rel), r.http_status,
                ("" if r.link_found is None else ("yes" if r.link_found else "no")),
                r.duplicate_status, r.link_type, r.assigned_user_label,
                da, pa, sas, spam,
                r.placement_date.isoformat() if r.placement_date else "",
                r.discovered_at.isoformat() if r.discovered_at else "",
                r.qa_completed_at.isoformat() if r.qa_completed_at else "",
                r.created_at.isoformat() if r.created_at else "",
            ])
            if len(rows_out) >= cap:
                truncated = has_more or False
                return _EXPORT_HEADERS, rows_out, truncated
        if not has_more:
            break
    return _EXPORT_HEADERS, rows_out, truncated


async def get_backlink(
    db: AsyncSession, ctx: AuthContext, backlink_id: uuid.UUID
) -> BacklinkRecord:
    bl = await db.get(BacklinkRecord, backlink_id)
    if bl is None or bl.workspace_id != ctx.workspace_id:
        raise NotFoundError("Backlink not found")
    ctx.assert_project(bl.project_id)
    return bl


async def get_detail(db: AsyncSession, ctx: AuthContext, backlink_id: uuid.UUID):
    bl = await get_backlink(db, ctx, backlink_id)
    issues = list(
        (
            await db.execute(
                select(BacklinkIssue)
                .where(BacklinkIssue.backlink_id == backlink_id)
                .order_by(BacklinkIssue.severity)
            )
        ).scalars().all()
    )
    latest = None
    if bl.latest_crawl_result_id is not None:
        latest = (
            await db.execute(
                select(CrawlResult)
                .where(CrawlResult.backlink_id == backlink_id)
                .order_by(CrawlResult.crawled_at.desc())
                .limit(1)
            )
        ).scalars().first()
    history = list(
        (
            await db.execute(
                select(BacklinkHistory)
                .where(BacklinkHistory.backlink_id == backlink_id)
                .order_by(BacklinkHistory.created_at.desc())
                .limit(50)
            )
        ).scalars().all()
    )
    return bl, issues, latest, history


async def list_duplicate_occurrences(
    db: AsyncSession, ctx: AuthContext, backlink_id: uuid.UUID
) -> list[BacklinkRecord]:
    """Other backlinks that share this one's identity (same source + target domain)."""
    bl = await get_backlink(db, ctx, backlink_id)
    if bl.link_identity_id is None:
        return []
    stmt = _scope(
        select(BacklinkRecord).where(
            BacklinkRecord.link_identity_id == bl.link_identity_id,
            BacklinkRecord.id != bl.id,
        ),
        ctx,
    ).order_by(BacklinkRecord.project_id.asc(), BacklinkRecord.id.asc()).limit(200)
    return list((await db.execute(stmt)).scalars().all())


async def list_assignment_history(
    db: AsyncSession, ctx: AuthContext, backlink_id: uuid.UUID
):
    """Assignment-change timeline for a backlink (newest first)."""
    from app.models.link_identity import AssignmentHistory

    await get_backlink(db, ctx, backlink_id)  # scope check
    return list(
        (
            await db.execute(
                select(AssignmentHistory)
                .where(AssignmentHistory.backlink_id == backlink_id)
                .order_by(AssignmentHistory.changed_at.desc())
                .limit(100)
            )
        ).scalars().all()
    )


async def update_backlink(
    db: AsyncSession, ctx: AuthContext, backlink_id: uuid.UUID, payload: BacklinkUpdate
) -> BacklinkRecord:
    bl = await get_backlink(db, ctx, backlink_id)
    data = payload.model_dump(exclude_unset=True)
    if "expected_target_url" in data and data["expected_target_url"]:
        norm = normalize_url(data["expected_target_url"])
        if norm.valid:
            bl.target_url_normalized = norm.normalized
            bl.target_domain = norm.registrable_domain
    if "assigned_user_label" in data:
        # Store a trimmed label (or NULL) so a whitespace-only value never becomes
        # its own "user" — keeps it in the "(unassigned)" bucket, matching imports.
        cleaned = (data["assigned_user_label"] or "").strip()
        if cleaned:
            # Roll a spelling variant up to its canonical person (KEVIN/Keven → Kevin).
            from app.services import employee_service

            amap = await employee_service.alias_map(db, ctx.workspace_id)
            cleaned = employee_service.normalize_label(cleaned, amap)
        data["assigned_user_label"] = cleaned or None
    # Track REAL changes only (old != new) so the history stays signal, not noise.
    changes: list[tuple[str, object, object]] = []
    for field, value in data.items():
        old = getattr(bl, field)
        if old != value:
            changes.append((field, old, value))
        setattr(bl, field, value)
    for field, old, new in changes:
        if field == "assigned_user_label":
            # Align the single-PATCH path with bulk_edit: a user change stamps
            # assigned_at + logs AssignmentHistory (feeds performance/tasks).
            from app.models.link_identity import AssignmentHistory

            bl.assigned_at = datetime.now(timezone.utc)
            db.add(AssignmentHistory(
                workspace_id=ctx.workspace_id, project_id=bl.project_id, backlink_id=bl.id,
                link_identity_id=bl.link_identity_id, old_user_label=old, new_user_label=new,
                source="ui",
            ))
    from app.services import history_service

    for field, old, new in changes:
        await history_service.record_link_event(
            db, backlink=bl, event_type=HistoryEventType.EDITED, field=field,
            old_value=old, new_value=new, actor_user_id=ctx.user.id,
            actor_role=ctx.role.value, source="ui",
        )
    await db.flush()
    return bl


BULK_EDIT_CAP = 2000


async def bulk_edit(
    db: AsyncSession, ctx: AuthContext, ids: list[uuid.UUID], *,
    set_user: bool, assigned_user_label: str | None,
    set_placement: bool, placement_date: date | None,
) -> int:
    """Set assigned_user_label and/or placement_date on many backlinks at once.
    Every row is scoped to the caller's workspace + allowed projects (out-of-scope
    ids are silently excluded), the label is canonicalized (blank→NULL) exactly like
    single-edit, and a user change stamps assigned_at + logs AssignmentHistory (feeds
    performance/tasks). Does NOT touch link identity (dedup is source-URL based)."""
    if not (set_user or set_placement):
        return 0
    ids = ids[:BULK_EDIT_CAP]
    if not ids:
        return 0
    from app.models.link_identity import AssignmentHistory
    from app.services import employee_service, history_service

    label: str | None = None
    if set_user:
        cleaned = (assigned_user_label or "").strip()
        if cleaned:
            amap = await employee_service.alias_map(db, ctx.workspace_id)
            cleaned = employee_service.normalize_label(cleaned, amap)
        label = cleaned or None

    rows = list(
        (await db.execute(_scope(select(BacklinkRecord).where(BacklinkRecord.id.in_(ids)), ctx)))
        .scalars().all()
    )
    now = datetime.now(timezone.utc)
    changed = 0
    for bl in rows:
        ctx.assert_project(bl.project_id)  # RBAC: refuse cross-project ids (fail-closed)
        touched = False
        if set_user and bl.assigned_user_label != label:
            old = bl.assigned_user_label
            bl.assigned_user_label = label
            bl.assigned_at = now
            db.add(AssignmentHistory(
                workspace_id=ctx.workspace_id, project_id=bl.project_id, backlink_id=bl.id,
                link_identity_id=bl.link_identity_id, old_user_label=old, new_user_label=label,
                source="ui",
            ))
            # One timeline event per row per action (coalesced, never per-cell spam).
            await history_service.record_link_event(
                db, backlink=bl, event_type=HistoryEventType.REASSIGNED,
                field="assigned_user_label", old_value=old, new_value=label,
                actor_user_id=ctx.user.id, actor_role=ctx.role.value, source="ui",
            )
            touched = True
        if set_placement and bl.placement_date != placement_date:
            old_placement = bl.placement_date
            bl.placement_date = placement_date
            await history_service.record_link_event(
                db, backlink=bl, event_type=HistoryEventType.EDITED,
                field="placement_date", old_value=old_placement, new_value=placement_date,
                actor_user_id=ctx.user.id, actor_role=ctx.role.value, source="ui",
            )
            touched = True
        if touched:
            changed += 1
    await db.flush()
    return changed


async def fill_missing_placement(
    db: AsyncSession, ctx: AuthContext, *,
    filters: BacklinkFilters | None = None, ids: list[uuid.UUID] | None = None,
) -> int:
    """Back-fill placement dates for links that have NONE, scoped to explicit ids OR
    the same grid filters. Opt-in / audited.

    The dates are *spread* across the real placement window of the surrounding scope
    (min…max of the links that already have a date) with a per-row random day, so the
    back-fill scatters naturally over the timeline instead of dumping every link on a
    single spike. When there is no usable window (no existing dates, or all on one
    day) each link falls back to its own import date (created_at, UTC)."""
    from sqlalchemy import Date, Integer, cast, literal
    from sqlalchemy import update as sa_update

    id_select = _scope(select(BacklinkRecord.id), ctx)
    if ids:
        id_select = id_select.where(BacklinkRecord.id.in_(ids[:BULK_EDIT_CAP]))
    elif filters is not None:
        id_select = _apply_filters(id_select, filters)
    id_select = id_select.where(BacklinkRecord.placement_date.is_(None))
    matching = list((await db.execute(id_select)).scalars().all())
    if not matching:
        return 0

    # Read the existing-placement span of the surrounding scope (the project when the
    # caller narrowed to one, else the whole accessible workspace) — NOT the null-only
    # filtered set, which by definition has no dates to spread across.
    rng = _scope(
        select(func.min(BacklinkRecord.placement_date), func.max(BacklinkRecord.placement_date)),
        ctx,
    )
    if filters is not None and filters.project_id:
        rng = rng.where(BacklinkRecord.project_id == filters.project_id)
    rng = rng.where(BacklinkRecord.placement_date.isnot(None))
    dmin, dmax = (await db.execute(rng)).one()

    upd = sa_update(BacklinkRecord).where(BacklinkRecord.id.in_(matching))
    if dmin is not None and dmax is not None and dmax > dmin:
        span = (dmax - dmin).days
        # random() is volatile → evaluated per row, so the filled dates scatter
        # uniformly over [dmin, dmax] (date + int-days is native in Postgres).
        rand_day = cast(func.floor(func.random() * (span + 1)), Integer)
        upd = upd.values(placement_date=cast(literal(dmin), Date) + rand_day)
    else:
        upd = upd.values(placement_date=cast(func.timezone("UTC", BacklinkRecord.created_at), Date))
    await db.execute(upd)
    return len(matching)


async def override_verdict(
    db: AsyncSession, ctx: AuthContext, backlink_id: uuid.UUID, status: OverallStatus, note: str
) -> BacklinkRecord:
    bl = await get_backlink(db, ctx, backlink_id)
    old_effective = bl.override_status or bl.status  # what the user saw before
    bl.override_status = status
    bl.override_note = note
    bl.overridden_by = ctx.user.id
    bl.overridden_at = datetime.now(timezone.utc)
    from app.services import history_service

    await history_service.record_link_event(
        db, backlink=bl,
        # Defensive: today's API always sends a status; a null would be a clear.
        event_type=(
            HistoryEventType.OVERRIDE_CLEARED if status is None
            else HistoryEventType.OVERRIDE_SET
        ),
        field="override_status", old_value=old_effective, new_value=status,
        actor_user_id=ctx.user.id, actor_role=ctx.role.value, source="ui", note=note,
    )
    await db.flush()
    return bl


async def create_backlink(
    db: AsyncSession, ctx: AuthContext, payload: BacklinkCreate
) -> BacklinkRecord:
    src = normalize_url(payload.source_page_url)
    tgt = normalize_url(payload.target_url)
    if not src.valid:
        raise PermissionDeniedError(f"Invalid source URL: {src.error}")
    if not tgt.valid:
        raise PermissionDeniedError(f"Invalid target URL: {tgt.error}")

    bl = BacklinkRecord(
        workspace_id=ctx.workspace_id,
        project_id=payload.project_id,
        source_page_url=payload.source_page_url,
        target_url=payload.target_url,
        expected_target_url=payload.expected_target_url or payload.target_url,
        expected_anchor_text=payload.expected_anchor_text,
        expected_rel=payload.expected_rel,
        client_name=payload.client_name,
        cost=payload.cost,
        placement_date=payload.placement_date,
        notes=payload.notes,
        tags=payload.tags,
        source_url_normalized=src.normalized,
        target_url_normalized=tgt.normalized,
        source_domain=src.registrable_domain,
        target_domain=tgt.registrable_domain,
        status=OverallStatus.PENDING,
        # Discovery = when the link first entered our DB; every insert path sets it.
        discovered_at=datetime.now(timezone.utc),
        next_check_at=datetime.now(timezone.utc),
    )
    db.add(bl)
    await db.flush()
    from app.services import history_service

    await history_service.record_link_event(
        db, backlink=bl, event_type=HistoryEventType.CREATED,
        new_value=bl.source_page_url, actor_user_id=ctx.user.id,
        actor_role=ctx.role.value, source="ui",
    )
    return bl
