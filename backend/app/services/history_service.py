"""Per-link history: manual-action event writer + merged timeline reads (Phase 10 P5).

``result_service`` emits the crawl-diff events; this module is the single writer
for MANUAL/ACTION events (created/edited/override/reassigned/deleted/rescored/
index+dedup flips) so every mutation path lands in the same ``backlink_history``
table with actor + provenance. It also serves the read side: the merged
newest-first timeline (``backlink_history`` + ``assignment_history`` normalized
into one shape) and the full crawl-check list, so repeated same-outcome checks
are all visible.

Depends on models only (no service imports) — every service can import it
without circular-import risk.
"""

from __future__ import annotations

import uuid
from datetime import datetime, timedelta, timezone

from sqlalchemy import or_, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.backlink import BacklinkRecord
from app.models.crawl import BacklinkHistory, CrawlResult
from app.models.enums import HistoryEventType
from app.models.link_identity import AssignmentHistory


def _now() -> datetime:
    return datetime.now(timezone.utc)


def _text(value: object) -> str | None:
    """Stringify a value the way history rows store it (enums by .value, None kept)."""
    if value is None:
        return None
    return str(getattr(value, "value", value))


async def record_event_for_ids(
    db: AsyncSession,
    *,
    backlink_id: uuid.UUID,
    workspace_id: uuid.UUID,
    project_id: uuid.UUID,
    event_type: HistoryEventType,
    field: str | None = None,
    old_value: object = None,
    new_value: object = None,
    score_delta: float | None = None,
    actor_user_id: uuid.UUID | None = None,
    actor_role: str | None = None,
    source: str = "system",
    note: str | None = None,
) -> BacklinkHistory:
    """Low-level insert for callers holding scalar ids (bulk UPDATE paths).

    ``created_at`` = now(): the maintenance beat pre-creates monthly partitions
    around 'now' and ``backlink_history_default`` catches anything else, so the
    row always lands in an existing partition (same guarantee result_service
    relies on).
    """
    ev = BacklinkHistory(
        created_at=_now(),
        backlink_id=backlink_id,
        workspace_id=workspace_id,
        project_id=project_id,
        event_type=event_type,
        field=field,
        old_value=_text(old_value),
        new_value=_text(new_value),
        score_delta=score_delta,
        actor_user_id=actor_user_id,
        actor_role=_text(actor_role)[:20] if actor_role is not None else None,
        source=source,
        note=note[:300] if note else None,
    )
    db.add(ev)
    return ev


async def record_link_event(
    db: AsyncSession,
    *,
    backlink: BacklinkRecord,
    event_type: HistoryEventType,
    field: str | None = None,
    old_value: object = None,
    new_value: object = None,
    score_delta: float | None = None,
    actor_user_id: uuid.UUID | None = None,
    actor_role: str | None = None,
    source: str = "system",
    note: str | None = None,
) -> BacklinkHistory:
    """Insert one manual-action history row for a loaded backlink (flushed by the
    caller's commit; never flushes itself so it composes into any transaction)."""
    return await record_event_for_ids(
        db,
        backlink_id=backlink.id,
        workspace_id=backlink.workspace_id,
        project_id=backlink.project_id,
        event_type=event_type,
        field=field,
        old_value=old_value,
        new_value=new_value,
        score_delta=score_delta,
        actor_user_id=actor_user_id,
        actor_role=actor_role,
        source=source,
        note=note,
    )


# ── Merged timeline (read side) ──────────────────────────────────────────────────

# A UI reassignment is dual-written (backlink_history event + assignment_history
# row, matching bulk_edit's established behaviour); when both describe the same
# change within this window the merged view keeps the richer history event.
_DEDUP_WINDOW = timedelta(seconds=5)

_REASSIGN_FIELDS = {"assigned_user_label"}


def _normalize_history(h: BacklinkHistory) -> dict:
    return {
        "at": h.created_at,
        "event_type": h.event_type.value,
        "severity": h.severity.value if h.severity else None,
        "field": h.field,
        "old_value": h.old_value,
        "new_value": h.new_value,
        "score_delta": h.score_delta,
        "actor_user_id": h.actor_user_id,
        "actor_role": h.actor_role,
        "source": h.source,
        "note": h.note,
    }


def _normalize_assignment(a: AssignmentHistory) -> dict:
    return {
        "at": a.changed_at,
        "event_type": HistoryEventType.REASSIGNED.value,
        "severity": None,
        "field": "assigned_user_label",
        "old_value": a.old_user_label,
        "new_value": a.new_user_label,
        "score_delta": None,
        "actor_user_id": None,  # assignment_history carries no actor column
        "actor_role": None,
        "source": a.source,
        "note": None,
    }


def _parse_event_types(event_type: str | None) -> list[HistoryEventType]:
    """Comma list → valid enum members; invalid parts are dropped (filter is
    skipped when nothing valid remains — same convention as the grid filters)."""
    if not event_type:
        return []
    return [
        HistoryEventType(p.strip())
        for p in event_type.split(",")
        if p.strip() in HistoryEventType._value2member_map_
    ]


async def list_history(
    db: AsyncSession,
    backlink_id: uuid.UUID,
    *,
    event_type: str | None = None,
    q: str | None = None,
    limit: int = 50,
    offset: int = 0,
) -> tuple[list[dict], bool]:
    """Merged newest-first timeline over backlink_history + assignment_history.

    Caller MUST have scope-checked the backlink already (the router uses
    ``backlink_service.get_backlink`` — same guard as the detail endpoint).
    Both sources are fetched filtered + bounded (offset+limit+1 each), merge-
    sorted desc, deduped, then sliced — correct limit/offset paging without
    scanning either table beyond the requested window.
    """
    limit = max(1, min(limit, 200))
    fetch = offset + limit + 1
    wanted = _parse_event_types(event_type)
    like = f"%{q.strip()}%" if q and q.strip() else None

    stmt = select(BacklinkHistory).where(BacklinkHistory.backlink_id == backlink_id)
    if wanted:
        stmt = stmt.where(BacklinkHistory.event_type.in_(wanted))
    if like:
        stmt = stmt.where(
            or_(
                BacklinkHistory.old_value.ilike(like),
                BacklinkHistory.new_value.ilike(like),
                BacklinkHistory.note.ilike(like),
            )
        )
    stmt = stmt.order_by(BacklinkHistory.created_at.desc()).limit(fetch)
    events = [_normalize_history(h) for h in (await db.execute(stmt)).scalars().all()]

    # Assignment rows surface as 'reassigned' — skip the query entirely when an
    # event_type filter excludes them.
    entries: list[dict] = events
    if not wanted or HistoryEventType.REASSIGNED in wanted:
        a_stmt = select(AssignmentHistory).where(AssignmentHistory.backlink_id == backlink_id)
        if like:
            a_stmt = a_stmt.where(
                or_(
                    AssignmentHistory.old_user_label.ilike(like),
                    AssignmentHistory.new_user_label.ilike(like),
                )
            )
        a_stmt = a_stmt.order_by(AssignmentHistory.changed_at.desc()).limit(fetch)
        assignments = [
            _normalize_assignment(a) for a in (await db.execute(a_stmt)).scalars().all()
        ]
        # Drop assignment entries that duplicate a same-change history event
        # written in the same transaction (dual-write on the UI paths).
        deduped = []
        for a in assignments:
            twin = any(
                e["field"] in _REASSIGN_FIELDS
                and e["old_value"] == a["old_value"]
                and e["new_value"] == a["new_value"]
                and abs(e["at"] - a["at"]) <= _DEDUP_WINDOW
                for e in events
            )
            if not twin:
                deduped.append(a)
        entries = events + deduped

    entries.sort(key=lambda e: e["at"], reverse=True)
    has_more = len(entries) > offset + limit
    return entries[offset : offset + limit], has_more


async def list_checks(
    db: AsyncSession,
    backlink_id: uuid.UUID,
    *,
    limit: int = 50,
    cursor: str | None = None,
) -> tuple[list[CrawlResult], str | None, bool]:
    """Keyset-paged crawl checks for a backlink, newest first — EVERY check row,
    so repeated same-outcome checks stay visible (the change-only history hides
    them by design). Cursor pairs (crawled_at, id) like the grid's keyset."""
    from sqlalchemy import and_

    from app.core.cursor import decode_cursor, encode_cursor

    limit = max(1, min(limit, 200))
    stmt = select(CrawlResult).where(CrawlResult.backlink_id == backlink_id)
    if cursor:
        raw_value, last_id = decode_cursor(cursor)
        value = datetime.fromisoformat(raw_value)
        stmt = stmt.where(
            or_(
                CrawlResult.crawled_at < value,
                and_(CrawlResult.crawled_at == value, CrawlResult.id < last_id),
            )
        )
    stmt = stmt.order_by(CrawlResult.crawled_at.desc(), CrawlResult.id.desc()).limit(limit + 1)
    rows = list((await db.execute(stmt)).scalars().all())

    has_more = len(rows) > limit
    rows = rows[:limit]
    next_cursor = None
    if has_more and rows:
        last = rows[-1]
        next_cursor = encode_cursor(last.crawled_at.isoformat(), last.id)
    return rows, next_cursor, has_more
