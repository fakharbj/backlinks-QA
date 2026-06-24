"""Backlink read/grid/detail/override logic.

The grid uses **keyset** pagination on an indexed ``(sort_col, id)`` pair so paging
stays constant-time at 1M+ rows. Tenant isolation (``workspace_id``) and project
scoping are injected into every query.
"""

from __future__ import annotations

import uuid
from datetime import datetime, timezone

from sqlalchemy import Select, and_, exists, func, or_, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.cursor import decode_cursor, encode_cursor
from app.core.deps import AuthContext
from app.core.errors import NotFoundError, PermissionDeniedError
from app.crawler.normalize import normalize_url, registrable_domain
from app.models.backlink import BacklinkRecord
from app.models.crawl import BacklinkHistory, BacklinkIssue, CrawlResult
from app.models.enums import OverallStatus, RelType
from app.schemas.backlink import BacklinkCreate, BacklinkFilters, BacklinkUpdate

_EPOCH = datetime(1970, 1, 1, tzinfo=timezone.utc)


def _scope(stmt: Select, ctx: AuthContext) -> Select:
    stmt = stmt.where(BacklinkRecord.workspace_id == ctx.workspace_id)
    if ctx.allowed_project_ids is not None:
        stmt = stmt.where(BacklinkRecord.project_id.in_(ctx.allowed_project_ids or {uuid.uuid4()}))
    return stmt


def _apply_filters(stmt: Select, f: BacklinkFilters) -> Select:
    if f.project_id:
        stmt = stmt.where(BacklinkRecord.project_id == f.project_id)
    if f.status:
        stmt = stmt.where(
            func.coalesce(BacklinkRecord.override_status, BacklinkRecord.status) == f.status
        )
    if f.score_min is not None:
        stmt = stmt.where(BacklinkRecord.score >= f.score_min)
    if f.score_max is not None:
        stmt = stmt.where(BacklinkRecord.score <= f.score_max)
    if f.rel:
        stmt = stmt.where(BacklinkRecord.current_rel == f.rel)
    if f.indexability:
        stmt = stmt.where(BacklinkRecord.indexability == f.indexability)
    if f.robots_status:
        stmt = stmt.where(BacklinkRecord.robots_status == f.robots_status)
    if f.canonical_status:
        stmt = stmt.where(BacklinkRecord.canonical_status == f.canonical_status)
    if f.vendor_id:
        stmt = stmt.where(BacklinkRecord.vendor_id == f.vendor_id)
    if f.campaign_id:
        stmt = stmt.where(BacklinkRecord.campaign_id == f.campaign_id)
    if f.assigned_user_id:
        stmt = stmt.where(BacklinkRecord.assigned_user_id == f.assigned_user_id)
    if f.assigned_user_label:
        stmt = stmt.where(BacklinkRecord.assigned_user_label == f.assigned_user_label)
    if f.link_type:
        stmt = stmt.where(BacklinkRecord.link_type == f.link_type)
    if f.duplicate_status:
        if f.duplicate_status == "duplicate":  # any duplicate
            stmt = stmt.where(BacklinkRecord.is_duplicate.is_(True))
        else:
            stmt = stmt.where(BacklinkRecord.duplicate_status == f.duplicate_status)
    if f.source_domain:
        stmt = stmt.where(BacklinkRecord.source_domain == f.source_domain.lower())
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
    if f.issue_label:
        stmt = stmt.where(
            exists().where(
                and_(
                    BacklinkIssue.backlink_id == BacklinkRecord.id,
                    BacklinkIssue.label == f.issue_label,
                )
            )
        )
    return stmt


def _sort_column(sort: str):
    if sort == "last_checked_at":
        return func.coalesce(BacklinkRecord.last_checked_at, _EPOCH)
    if sort == "created_at":
        return BacklinkRecord.created_at
    return func.coalesce(BacklinkRecord.score, -1)  # default: score


def _parse_cursor_value(sort: str, raw: str):
    if sort in ("last_checked_at", "created_at"):
        return datetime.fromisoformat(raw)
    return int(raw)


async def list_backlinks(
    db: AsyncSession,
    ctx: AuthContext,
    filters: BacklinkFilters,
    *,
    sort: str = "score",
    limit: int = 50,
    cursor: str | None = None,
) -> tuple[list[BacklinkRecord], str | None, bool]:
    limit = max(1, min(limit, 200))
    sort_col = _sort_column(sort)

    stmt = _apply_filters(_scope(select(BacklinkRecord), ctx), filters)

    if cursor:
        raw_value, last_id = decode_cursor(cursor)
        value = _parse_cursor_value(sort, raw_value)
        # Descending keyset: (sort, id) strictly less than the cursor tuple.
        stmt = stmt.where(
            or_(sort_col < value, and_(sort_col == value, BacklinkRecord.id < last_id))
        )

    stmt = stmt.order_by(sort_col.desc(), BacklinkRecord.id.desc()).limit(limit + 1)
    rows = list((await db.execute(stmt)).scalars().all())

    has_more = len(rows) > limit
    rows = rows[:limit]
    next_cursor = None
    if has_more and rows:
        last = rows[-1]
        if sort == "score":
            sort_value: object = last.score if last.score is not None else -1
        elif sort == "last_checked_at":
            sort_value = (last.last_checked_at or _EPOCH).isoformat()
        else:
            sort_value = last.created_at.isoformat()
        next_cursor = encode_cursor(sort_value, last.id)
    return rows, next_cursor, has_more


async def count_backlinks(db: AsyncSession, ctx: AuthContext, filters: BacklinkFilters) -> int:
    stmt = _apply_filters(_scope(select(func.count(BacklinkRecord.id)), ctx), filters)
    return int((await db.execute(stmt)).scalar_one())


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
    for field, value in data.items():
        setattr(bl, field, value)
    await db.flush()
    return bl


async def override_verdict(
    db: AsyncSession, ctx: AuthContext, backlink_id: uuid.UUID, status: OverallStatus, note: str
) -> BacklinkRecord:
    bl = await get_backlink(db, ctx, backlink_id)
    bl.override_status = status
    bl.override_note = note
    bl.overridden_by = ctx.user.id
    bl.overridden_at = datetime.now(timezone.utc)
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
        next_check_at=datetime.now(timezone.utc),
    )
    db.add(bl)
    await db.flush()
    return bl
