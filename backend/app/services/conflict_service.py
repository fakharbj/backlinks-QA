"""Backlink conflict (duplicate) detection + resolution (Phase 8, feature 9).

A conflict groups backlinks that share the same canonical source URL
(``canonical_url_id``) within a workspace. ``classify_scope`` is a pure rule
(unit-tested). ``rebuild_workspace`` recomputes every group from current data
(preserving prior resolution decisions); ``resolve`` records the review outcome.

Detection keys off the indexed ``canonical_url_id``, so it scales without scanning
the backlink table.

Enterprise (migration 0034) adds pure comparison helpers (``field_matrix``,
``similarity_score``, ``duplicate_reason``), enriched member facts, a per-group
detail view, expanded whitelist filters, and bulk / resolution actions with an
append-only ``backlink_conflict_actions`` audit trail.
"""

from __future__ import annotations

import uuid
from datetime import date, datetime, timezone
from typing import Any

from sqlalchemy import String, cast, delete, exists, func, or_, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.deps import AuthContext
from app.core.errors import NotFoundError, ValidationAppError
from app.models.backlink import BacklinkRecord
from app.models.canonical_url import CanonicalUrl
from app.models.conflict import (
    BacklinkConflict,
    BacklinkConflictAction,
    BacklinkConflictMember,
)
from app.models.project import Project

SAME_PROJECT = "same_project"
CROSS_PROJECT = "cross_project"
CROSS_USER = "cross_user"

_KEEP_STATUSES = ("acknowledged", "resolved", "ignored")

# Comparable member fields → their weight in the similarity score. ``source_domain``
# is the baseline (all group members share a canonical source URL, so it is always
# the same) and does not add points; the rest add points for AGREEMENT so a tight
# group scores high and a sprawling cross-project/user one scores low.
_SIMILARITY_WEIGHTS = {
    "target_url_normalized": 30,
    "anchor": 20,
    "rel": 15,
    "project_id": 15,
    "assigned_user_label": 10,
    "link_type": 10,
}
_SIMILARITY_TOTAL = sum(_SIMILARITY_WEIGHTS.values())  # 100

# Whitelisted list/detail sort + filter surface (bind real values only).
_LIST_SCOPES = {SAME_PROJECT, CROSS_PROJECT, CROSS_USER, "competitor_vs_project"}
_LIST_STATUSES = {"open", "acknowledged", "resolved", "ignored"}
_BULK_ACTIONS = {
    "resolve": "resolved",
    "acknowledge": "acknowledged",
    "ignore": "ignored",
    "reopen": "open",
}

_MEMBER_DETAIL_CAP = 50


def classify_scope(project_count: int, user_count: int) -> str:
    """Pure rule (unit-tested): spanning projects > spanning users > same project."""
    if project_count > 1:
        return CROSS_PROJECT
    if user_count > 1:
        return CROSS_USER
    return SAME_PROJECT


# ── Pure comparison helpers (deterministic, DB-free, unit-testable) ──────────

def _coalesce(a: Any, b: Any) -> Any:
    """First non-empty of (a, b). Empty string counts as absent."""
    if a not in (None, ""):
        return a
    if b not in (None, ""):
        return b
    return None


# The comparable fields, in a stable display order. Each entry maps a logical
# field name to a callable pulling its value from a member dict.
_MATRIX_FIELDS: tuple[tuple[str, Any], ...] = (
    ("source_domain", lambda m: m.get("source_domain")),
    ("target_url_normalized", lambda m: m.get("target_url_normalized")),
    ("target_domain", lambda m: m.get("target_domain")),
    ("anchor", lambda m: _coalesce(m.get("current_anchor_text"), m.get("expected_anchor_text"))),
    ("rel", lambda m: _coalesce(m.get("current_rel"), m.get("expected_rel"))),
    ("project_id", lambda m: str(m["project_id"]) if m.get("project_id") else None),
    ("assigned_user_label", lambda m: m.get("assigned_user_label")),
    ("link_type", lambda m: m.get("link_type")),
    ("placement_date", lambda m: m.get("placement_date").isoformat()
     if isinstance(m.get("placement_date"), (date, datetime)) else m.get("placement_date")),
)


def field_matrix(members: list[dict]) -> list[dict]:
    """Per comparable field, whether every member agrees + a distinct-value sample.

    Pure: takes already-loaded member dicts, returns a list of
    ``{field, all_same, distinct, values}`` rows (values is a small sample of the
    distinct values, blanks rendered as ``None``). Deterministic ordering.
    """
    out: list[dict] = []
    for name, getter in _MATRIX_FIELDS:
        seen: list[Any] = []
        for m in members:
            v = getter(m)
            v = v if v not in ("",) else None
            if v not in seen:
                seen.append(v)
        out.append(
            {
                "field": name,
                "all_same": len(seen) <= 1,
                "distinct": len(seen),
                "values": seen[:6],
            }
        )
    return out


def similarity_score(matrix: list[dict]) -> int:
    """0-100 weighted agreement across the comparison matrix (higher = tighter).

    A field contributes its full weight when every member agrees (``all_same``),
    zero otherwise. ``source_domain`` is the shared baseline and carries no weight.
    Normalized to 0-100 over the weighted fields. Pure + deterministic.
    """
    by_field = {row["field"]: row for row in matrix}
    earned = 0
    for field, weight in _SIMILARITY_WEIGHTS.items():
        row = by_field.get(field)
        if row is not None and row.get("all_same"):
            earned += weight
    if _SIMILARITY_TOTAL == 0:
        return 100
    return round(earned * 100 / _SIMILARITY_TOTAL)


def duplicate_reason(scope: str, matrix: list[dict], member_count: int) -> str:
    """Human sentence explaining why the group is a conflict. Pure + deterministic."""
    by_field = {row["field"]: row for row in matrix}
    n = member_count
    if scope == CROSS_PROJECT:
        head = f"Same source page linked from {n} records across multiple projects"
    elif scope == CROSS_USER:
        head = f"Same source page assigned to different users across {n} records"
    elif scope == "competitor_vs_project":
        head = f"Source page appears in both competitor and project data ({n} records)"
    else:
        head = f"Same source page appears in {n} records within one project"

    diffs = [
        label
        for field, label in (
            ("target_url_normalized", "target URL"),
            ("anchor", "anchor text"),
            ("rel", "rel attribute"),
            ("link_type", "link type"),
            ("assigned_user_label", "assigned user"),
        )
        if not by_field.get(field, {}).get("all_same", True)
    ]
    if diffs:
        if len(diffs) == 1:
            tail = f" — the {diffs[0]} differs between them."
        else:
            tail = f" — the {', '.join(diffs[:-1])} and {diffs[-1]} differ between them."
    else:
        tail = " — the records are otherwise identical."
    return head + tail


def _facts_from_members(members: list[dict]) -> dict:
    """Compute reason/similarity/first_member/distinct rollups from member dicts.

    ``first_member_id`` = suggested keep = highest score then oldest created_at.
    Pure over the loaded members (no DB).
    """
    matrix = field_matrix(members)
    projects = {str(m["project_id"]) for m in members if m.get("project_id")}
    users = {
        (m.get("assigned_user_label") or "").strip()
        for m in members
        if (m.get("assigned_user_label") or "").strip()
    }
    targets = {m.get("target_url_normalized") for m in members if m.get("target_url_normalized")}
    scope = classify_scope(len(projects), len(users))

    def _keep_key(m: dict):
        score = m.get("score")
        created = m.get("created_at") or datetime.max.replace(tzinfo=timezone.utc)
        # Highest score first (score None → -1), then oldest created_at.
        return (-(score if score is not None else -1), created)

    keep = min(members, key=_keep_key) if members else None
    return {
        "matrix": matrix,
        "similarity": similarity_score(matrix),
        "reason": duplicate_reason(scope, matrix, len(members)),
        "first_member_id": (keep or {}).get("backlink_id"),
        "distinct_projects": len(projects),
        "distinct_users": len(users),
        "distinct_targets": len(targets),
    }


# ── Enriched member loading ──────────────────────────────────────────────────

async def _members(db: AsyncSession, conflict_ids: list[uuid.UUID]) -> dict[uuid.UUID, list[dict]]:
    if not conflict_ids:
        return {}
    rows = (
        await db.execute(
            select(
                BacklinkConflictMember.conflict_id,
                BacklinkRecord.id,
                BacklinkRecord.project_id,
                Project.name,
                BacklinkRecord.source_page_url,
                BacklinkRecord.target_url,
                BacklinkRecord.status,
                BacklinkRecord.score,
                BacklinkRecord.assigned_user_label,
                BacklinkRecord.link_type,
                BacklinkRecord.source_domain,
                BacklinkRecord.current_anchor_text,
                BacklinkRecord.expected_anchor_text,
                BacklinkRecord.current_rel,
                BacklinkRecord.expected_rel,
                BacklinkRecord.target_url_normalized,
                BacklinkRecord.target_domain,
                BacklinkRecord.index_status,
                BacklinkRecord.duplicate_status,
                BacklinkRecord.is_duplicate,
                BacklinkRecord.placement_date,
                BacklinkRecord.created_at,
                BacklinkRecord.last_checked_at,
                BacklinkRecord.override_status,
            )
            .join(BacklinkRecord, BacklinkRecord.id == BacklinkConflictMember.backlink_id)
            .outerjoin(Project, Project.id == BacklinkRecord.project_id)
            .where(BacklinkConflictMember.conflict_id.in_(conflict_ids))
        )
    ).all()
    out: dict[uuid.UUID, list[dict]] = {}
    for r in rows:
        out.setdefault(r[0], []).append(
            {
                "backlink_id": r[1],
                "project_id": r[2],
                "project_name": r[3],
                "source_page_url": r[4],
                "target_url": r[5],
                "status": r[6].value if r[6] is not None else None,
                "score": r[7],
                "assigned_user_label": r[8],
                "link_type": r[9],
                "source_domain": r[10],
                "current_anchor_text": r[11],
                "expected_anchor_text": r[12],
                "current_rel": r[13].value if r[13] is not None else None,
                "expected_rel": r[14].value if r[14] is not None else None,
                "target_url_normalized": r[15],
                "target_domain": r[16],
                "index_status": r[17],
                "duplicate_status": r[18],
                "is_duplicate": r[19],
                "placement_date": r[20],
                "created_at": r[21],
                "last_checked_at": r[22],
                "override_status": r[23].value if r[23] is not None else None,
            }
        )
    return out


# ── Detection / rebuild (populate enterprise facts) ──────────────────────────

async def rebuild_workspace(db: AsyncSession, workspace_id: uuid.UUID) -> int:
    """Recompute all conflict groups for a workspace from current backlinks.

    Idempotent. Any canonical source URL referenced by >= 2 backlinks becomes a
    group. Prior resolution decisions are carried over for groups that still exist.
    Returns the number of groups.
    """
    # Remember prior resolutions so a re-scan doesn't wipe human decisions.
    prev_rows = (
        await db.execute(
            select(
                BacklinkConflict.canonical_url_id,
                BacklinkConflict.resolution_status,
                BacklinkConflict.resolved_by,
                BacklinkConflict.resolved_at,
            ).where(BacklinkConflict.workspace_id == workspace_id)
        )
    ).all()
    prev = {r.canonical_url_id: r for r in prev_rows}

    # Clear existing groups (members cascade via FK ondelete).
    await db.execute(
        delete(BacklinkConflict).where(BacklinkConflict.workspace_id == workspace_id)
    )

    groups = (
        await db.execute(
            select(
                BacklinkRecord.canonical_url_id,
                func.count().label("members"),
                func.count(func.distinct(BacklinkRecord.project_id)).label("projects"),
                func.count(
                    func.distinct(func.nullif(BacklinkRecord.assigned_user_label, ""))
                ).label("users"),
                func.min(cast(BacklinkRecord.project_id, String)).label("any_project"),
            )
            .where(
                BacklinkRecord.workspace_id == workspace_id,
                BacklinkRecord.canonical_url_id.is_not(None),
            )
            .group_by(BacklinkRecord.canonical_url_id)
            .having(func.count() > 1)
        )
    ).all()

    now = datetime.now(timezone.utc)
    count = 0
    for g in groups:
        p = prev.get(g.canonical_url_id)
        keep = p.resolution_status if (p and p.resolution_status in _KEEP_STATUSES) else "open"
        conflict = BacklinkConflict(
            workspace_id=workspace_id,
            canonical_url_id=g.canonical_url_id,
            project_id=(uuid.UUID(g.any_project) if g.projects == 1 and g.any_project else None),
            scope=classify_scope(g.projects, g.users),
            resolution_status=keep,
            member_count=g.members,
            detected_at=now,
            resolved_by=(p.resolved_by if (p and keep in ("resolved", "ignored")) else None),
            resolved_at=(p.resolved_at if (p and keep in ("resolved", "ignored")) else None),
        )
        db.add(conflict)
        await db.flush()
        member_ids = (
            await db.execute(
                select(BacklinkRecord.id).where(
                    BacklinkRecord.workspace_id == workspace_id,
                    BacklinkRecord.canonical_url_id == g.canonical_url_id,
                )
            )
        ).scalars().all()
        for bid in member_ids:
            db.add(BacklinkConflictMember(conflict_id=conflict.id, backlink_id=bid))
        count += 1

    await db.flush()
    # One extra pass to populate the enterprise fact columns from loaded members.
    await _populate_facts(db, [c[0] for c in (
        await db.execute(
            select(BacklinkConflict.id).where(BacklinkConflict.workspace_id == workspace_id)
        )
    ).all()])
    await db.flush()
    return count


async def detect_for_canonicals(
    db: AsyncSession, workspace_id: uuid.UUID, canonical_ids: set[uuid.UUID]
) -> int:
    """Re-evaluate conflict groups for specific canonical source URLs (targeted).

    Called after an import so newly-stored duplicates surface immediately, without
    a full-workspace rebuild (safe under concurrent per-sheet syncs). Idempotent
    per canonical.
    """
    ids = [c for c in canonical_ids if c is not None]
    if not ids:
        return 0
    rows = (
        await db.execute(
            select(
                BacklinkRecord.canonical_url_id,
                func.count().label("members"),
                func.count(func.distinct(BacklinkRecord.project_id)).label("projects"),
                func.count(
                    func.distinct(func.nullif(BacklinkRecord.assigned_user_label, ""))
                ).label("users"),
                func.min(cast(BacklinkRecord.project_id, String)).label("any_project"),
            )
            .where(
                BacklinkRecord.workspace_id == workspace_id,
                BacklinkRecord.canonical_url_id.in_(ids),
            )
            .group_by(BacklinkRecord.canonical_url_id)
        )
    ).all()
    counts = {r.canonical_url_id: r for r in rows}
    now = datetime.now(timezone.utc)
    changed = 0
    touched: list[uuid.UUID] = []
    for cid in ids:
        existing = (
            await db.execute(
                select(BacklinkConflict).where(
                    BacklinkConflict.workspace_id == workspace_id,
                    BacklinkConflict.canonical_url_id == cid,
                )
            )
        ).scalar_one_or_none()
        r = counts.get(cid)
        members = r.members if r else 0
        if members <= 1:
            # No longer a conflict → drop the group (members cascade).
            if existing is not None:
                await db.execute(delete(BacklinkConflict).where(BacklinkConflict.id == existing.id))
                changed += 1
            continue
        scope = classify_scope(r.projects, r.users)
        project_id = uuid.UUID(r.any_project) if r.projects == 1 and r.any_project else None
        if existing is None:
            conflict = BacklinkConflict(
                workspace_id=workspace_id, canonical_url_id=cid, project_id=project_id,
                scope=scope, resolution_status="open", member_count=members, detected_at=now,
            )
            db.add(conflict)
            await db.flush()
        else:
            existing.scope = scope
            existing.member_count = members
            existing.project_id = project_id
            conflict = existing
            await db.execute(
                delete(BacklinkConflictMember).where(
                    BacklinkConflictMember.conflict_id == conflict.id
                )
            )
        member_ids = (
            await db.execute(
                select(BacklinkRecord.id).where(
                    BacklinkRecord.workspace_id == workspace_id,
                    BacklinkRecord.canonical_url_id == cid,
                )
            )
        ).scalars().all()
        for bid in member_ids:
            db.add(BacklinkConflictMember(conflict_id=conflict.id, backlink_id=bid))
        touched.append(conflict.id)
        changed += 1
    await db.flush()
    await _populate_facts(db, touched)
    await db.flush()
    return changed


async def _populate_facts(db: AsyncSession, conflict_ids: list[uuid.UUID]) -> None:
    """One extra pass over already-loaded members → set the fact columns.

    Idempotent per canonical: recomputes reason/similarity/first_member_id +
    distinct rollups from current member data. Uses ``_members`` so it reuses the
    same enriched select (no per-group N+1).
    """
    if not conflict_ids:
        return
    members_by = await _members(db, conflict_ids)
    conflicts = (
        await db.execute(
            select(BacklinkConflict).where(BacklinkConflict.id.in_(conflict_ids))
        )
    ).scalars().all()
    for c in conflicts:
        members = members_by.get(c.id, [])
        if not members:
            continue
        facts = _facts_from_members(members)
        c.reason = facts["reason"]
        c.similarity = facts["similarity"]
        c.first_member_id = facts["first_member_id"]
        c.distinct_projects = facts["distinct_projects"]
        c.distinct_users = facts["distinct_users"]
        c.distinct_targets = facts["distinct_targets"]


# ── Read: summary ────────────────────────────────────────────────────────────

async def summary(db: AsyncSession, ctx: AuthContext) -> dict:
    rows = (
        await db.execute(
            select(
                BacklinkConflict.resolution_status,
                BacklinkConflict.scope,
                func.count(),
                func.sum(func.greatest(BacklinkConflict.member_count - 1, 0)),
                func.avg(BacklinkConflict.similarity),
            )
            .where(BacklinkConflict.workspace_id == ctx.workspace_id)
            .group_by(BacklinkConflict.resolution_status, BacklinkConflict.scope)
        )
    ).all()
    total = open_ = resolved = 0
    dup_links = 0
    sim_sum = 0.0
    sim_n = 0
    by_scope: dict[str, int] = {}
    by_status: dict[str, int] = {}
    for status, scope, n, extra, avg_sim in rows:
        total += n
        if status == "open":
            open_ += n
        if status == "resolved":
            resolved += n
        by_scope[scope] = by_scope.get(scope, 0) + n
        by_status[status] = by_status.get(status, 0) + n
        dup_links += int(extra or 0)
        if avg_sim is not None:
            sim_sum += float(avg_sim) * n
            sim_n += n

    # Trend: duplicate groups first found per week (last 12 weeks) for the chart.
    from sqlalchemy import text as _text

    weekly = [
        dict(r)
        for r in (
            await db.execute(
                _text(
                    "SELECT to_char(date_trunc('week', detected_at), 'YYYY-MM-DD') AS week, "
                    "count(*) AS new_groups "
                    "FROM backlink_conflicts "
                    "WHERE workspace_id = :ws AND detected_at >= now() - interval '84 days' "
                    "GROUP BY 1 ORDER BY 1"
                ),
                {"ws": ctx.workspace_id},
            )
        ).mappings().all()
    ]
    return {
        "total": total, "open": open_, "resolved": resolved,
        "by_scope": by_scope, "by_status": by_status,
        "avg_similarity": round(sim_sum / sim_n, 1) if sim_n else None,
        "total_duplicate_links": dup_links,
        "weekly": weekly,
    }


# ── Read: list (expanded whitelist filters, offset + total) ──────────────────

def _csv(value: str | None) -> list[str]:
    return [p.strip() for p in str(value or "").split(",") if p.strip()]


def _project_scope_clause(ctx: AuthContext):
    """RBAC visibility for a project-scoped principal.

    A group is visible when EITHER its ``project_id`` is one they may see, OR the
    group spans projects (``project_id IS NULL``) but at least one member backlink
    belongs to one of their projects. This exposes cross-project duplicates
    read-only to the managers whose project is involved (previously hidden).
    """
    if ctx.allowed_project_ids is None:
        return None
    allowed = ctx.allowed_project_ids or {uuid.uuid4()}
    member_in_scope = exists(
        select(BacklinkConflictMember.id)
        .join(BacklinkRecord, BacklinkRecord.id == BacklinkConflictMember.backlink_id)
        .where(
            BacklinkConflictMember.conflict_id == BacklinkConflict.id,
            BacklinkRecord.project_id.in_(allowed),
        )
    )
    return or_(
        BacklinkConflict.project_id.in_(allowed),
        member_in_scope,
    )


def _list_where(
    ctx: AuthContext,
    *,
    scope: str | None,
    status: str | None,
    project_id: str | None,
    user: str | None,
    detected_from: date | datetime | None,
    detected_to: date | datetime | None,
    min_members: int | None,
    min_similarity: int | None,
    max_similarity: int | None,
    target_domain: str | None,
    source_page: str | None = None,
    created_from: date | datetime | None = None,
    created_to: date | datetime | None = None,
    search: str | None = None,
) -> list:
    """Build the whitelisted WHERE clauses (bind real values; no raw casts)."""
    clauses = [BacklinkConflict.workspace_id == ctx.workspace_id]

    scope_vals = [s for s in _csv(scope) if s in _LIST_SCOPES]
    if scope_vals:
        clauses.append(BacklinkConflict.scope.in_(scope_vals))

    status_vals = [s for s in _csv(status) if s in _LIST_STATUSES]
    if status_vals:
        clauses.append(BacklinkConflict.resolution_status.in_(status_vals))

    if min_members is not None:
        clauses.append(BacklinkConflict.member_count >= int(min_members))
    if min_similarity is not None:
        clauses.append(BacklinkConflict.similarity >= int(min_similarity))
    if max_similarity is not None:
        clauses.append(BacklinkConflict.similarity <= int(max_similarity))

    if detected_from is not None:
        clauses.append(BacklinkConflict.detected_at >= detected_from)
    if detected_to is not None:
        clauses.append(BacklinkConflict.detected_at <= detected_to)

    if search:
        clauses.append(CanonicalUrl.canonical_url.ilike(f"%{search.strip()}%"))

    # Member-scoped filters via EXISTS over members + backlink (bind real values).
    proj_vals: list[uuid.UUID] = []
    for p in _csv(project_id):
        try:
            proj_vals.append(uuid.UUID(p))
        except ValueError:
            continue
    if proj_vals:
        clauses.append(
            exists(
                select(BacklinkConflictMember.id)
                .join(BacklinkRecord, BacklinkRecord.id == BacklinkConflictMember.backlink_id)
                .where(
                    BacklinkConflictMember.conflict_id == BacklinkConflict.id,
                    BacklinkRecord.project_id.in_(proj_vals),
                )
            )
        )

    user_vals = _csv(user)
    if user_vals:
        clauses.append(
            exists(
                select(BacklinkConflictMember.id)
                .join(BacklinkRecord, BacklinkRecord.id == BacklinkConflictMember.backlink_id)
                .where(
                    BacklinkConflictMember.conflict_id == BacklinkConflict.id,
                    BacklinkRecord.assigned_user_label.in_(user_vals),
                )
            )
        )

    td_vals = [t.lower() for t in _csv(target_domain)]
    if td_vals:
        clauses.append(
            exists(
                select(BacklinkConflictMember.id)
                .join(BacklinkRecord, BacklinkRecord.id == BacklinkConflictMember.backlink_id)
                .where(
                    BacklinkConflictMember.conflict_id == BacklinkConflict.id,
                    func.lower(BacklinkRecord.target_domain).in_(td_vals),
                )
            )
        )

    # Source page: multiselect + searchable — each value is a substring match,
    # OR'd together (pick a full URL from the list, or type a partial).
    sp_vals = [s.strip() for s in _csv(source_page) if s.strip()]
    if sp_vals:
        clauses.append(
            exists(
                select(BacklinkConflictMember.id)
                .join(BacklinkRecord, BacklinkRecord.id == BacklinkConflictMember.backlink_id)
                .where(
                    BacklinkConflictMember.conflict_id == BacklinkConflict.id,
                    or_(*[BacklinkRecord.source_page_url.ilike(f"%{v}%") for v in sp_vals]),
                )
            )
        )

    # Date filter = the backlink's real CREATION/placement day (not detection/import).
    if created_from is not None or created_to is not None:
        member_date = func.coalesce(BacklinkRecord.placement_date, func.date(BacklinkRecord.created_at))
        date_clauses = [
            BacklinkConflictMember.conflict_id == BacklinkConflict.id,
        ]
        if created_from is not None:
            date_clauses.append(member_date >= created_from)
        if created_to is not None:
            date_clauses.append(member_date <= created_to)
        clauses.append(
            exists(
                select(BacklinkConflictMember.id)
                .join(BacklinkRecord, BacklinkRecord.id == BacklinkConflictMember.backlink_id)
                .where(*date_clauses)
            )
        )

    rbac = _project_scope_clause(ctx)
    if rbac is not None:
        clauses.append(rbac)
    return clauses


async def list_conflicts(
    db: AsyncSession,
    ctx: AuthContext,
    *,
    scope: str | None = None,
    status: str | None = None,
    project_id: str | None = None,
    user: str | None = None,
    detected_from: date | datetime | None = None,
    detected_to: date | datetime | None = None,
    min_members: int | None = None,
    min_similarity: int | None = None,
    max_similarity: int | None = None,
    target_domain: str | None = None,
    source_page: str | None = None,
    created_from: date | datetime | None = None,
    created_to: date | datetime | None = None,
    search: str | None = None,
    limit: int = 100,
    offset: int = 0,
) -> dict:
    """Offset + total list of conflict groups with expanded whitelist filters."""
    limit = max(1, min(int(limit or 100), 500))
    offset = max(0, int(offset or 0))
    clauses = _list_where(
        ctx, scope=scope, status=status, project_id=project_id, user=user,
        detected_from=detected_from, detected_to=detected_to, min_members=min_members,
        min_similarity=min_similarity, max_similarity=max_similarity,
        target_domain=target_domain, source_page=source_page,
        created_from=created_from, created_to=created_to, search=search,
    )

    total = (
        await db.execute(
            select(func.count())
            .select_from(BacklinkConflict)
            .outerjoin(CanonicalUrl, CanonicalUrl.id == BacklinkConflict.canonical_url_id)
            .where(*clauses)
        )
    ).scalar_one()

    stmt = (
        select(BacklinkConflict, CanonicalUrl.canonical_url, CanonicalUrl.fingerprint)
        .outerjoin(CanonicalUrl, CanonicalUrl.id == BacklinkConflict.canonical_url_id)
        .where(*clauses)
        .order_by(
            BacklinkConflict.member_count.desc(), BacklinkConflict.detected_at.desc()
        )
        .limit(limit)
        .offset(offset)
    )
    rows = (await db.execute(stmt)).all()
    members_by_conflict = await _members(db, [c.id for c, _u, _f in rows])

    items: list[dict] = []
    for conflict, canonical_url, fingerprint in rows:
        items.append(_group_dict(conflict, canonical_url, fingerprint,
                                 members_by_conflict.get(conflict.id, [])))
    return {"items": items, "total": total, "limit": limit, "offset": offset}


def _group_dict(conflict: BacklinkConflict, canonical_url, fingerprint, members: list[dict]) -> dict:
    return {
        "id": conflict.id,
        "canonical_url": canonical_url,
        "fingerprint": fingerprint,
        "project_id": conflict.project_id,
        "scope": conflict.scope,
        "resolution_status": conflict.resolution_status,
        "member_count": conflict.member_count,
        "detected_at": conflict.detected_at,
        "created_at": conflict.created_at,
        "reason": conflict.reason,
        "similarity": conflict.similarity,
        "first_member_id": conflict.first_member_id,
        "distinct_projects": conflict.distinct_projects,
        "distinct_users": conflict.distinct_users,
        "distinct_targets": conflict.distinct_targets,
        "members": members,
    }


# ── Read: detail ─────────────────────────────────────────────────────────────

async def _load_group(db: AsyncSession, ctx: AuthContext, conflict_id: uuid.UUID):
    """Fetch a group + canonical, enforcing workspace + RBAC visibility."""
    clauses = [
        BacklinkConflict.id == conflict_id,
        BacklinkConflict.workspace_id == ctx.workspace_id,
    ]
    rbac = _project_scope_clause(ctx)
    if rbac is not None:
        clauses.append(rbac)
    row = (
        await db.execute(
            select(BacklinkConflict, CanonicalUrl.canonical_url, CanonicalUrl.fingerprint)
            .outerjoin(CanonicalUrl, CanonicalUrl.id == BacklinkConflict.canonical_url_id)
            .where(*clauses)
        )
    ).first()
    if row is None:
        raise NotFoundError("Conflict not found")
    return row


async def get_detail(db: AsyncSession, ctx: AuthContext, conflict_id: uuid.UUID) -> dict:
    """Group + enriched members + field_matrix + similarity + reason + actions.

    Computes the matrix/reason live if the stored columns are null (legacy
    fallback). Caps members shown for huge groups (top ~50 by score) + notes total.
    """
    conflict, canonical_url, fingerprint = await _load_group(db, ctx, conflict_id)
    members = (await _members(db, [conflict.id])).get(conflict.id, [])
    total_members = len(members)

    facts = _facts_from_members(members) if members else {
        "matrix": [], "similarity": None, "reason": None, "first_member_id": None,
        "distinct_projects": 0, "distinct_users": 0, "distinct_targets": 0,
    }

    # Cap huge groups: keep the top N by score (desc) then oldest created_at.
    truncated = False
    shown = members
    if total_members > _MEMBER_DETAIL_CAP:
        shown = sorted(
            members,
            key=lambda m: (
                -(m.get("score") if m.get("score") is not None else -1),
                m.get("created_at") or datetime.max.replace(tzinfo=timezone.utc),
            ),
        )[:_MEMBER_DETAIL_CAP]
        truncated = True

    actions = await list_actions(db, ctx, conflict.id)

    base = _group_dict(conflict, canonical_url, fingerprint, shown)
    # Prefer stored facts; fall back to freshly computed ones for legacy rows.
    base["reason"] = conflict.reason or facts["reason"]
    base["similarity"] = conflict.similarity if conflict.similarity is not None else facts["similarity"]
    base["first_member_id"] = conflict.first_member_id or facts["first_member_id"]
    base["distinct_projects"] = (
        conflict.distinct_projects if conflict.distinct_projects is not None
        else facts["distinct_projects"]
    )
    base["distinct_users"] = (
        conflict.distinct_users if conflict.distinct_users is not None else facts["distinct_users"]
    )
    base["distinct_targets"] = (
        conflict.distinct_targets if conflict.distinct_targets is not None
        else facts["distinct_targets"]
    )
    base.update(
        {
            "field_matrix": facts["matrix"],
            "suggested_keep": base["first_member_id"],
            "actions": actions,
            "total_members": total_members,
            "members_truncated": truncated,
        }
    )
    return base


# ── Actions (audit trail + resolution) ───────────────────────────────────────

async def _record_action(
    db: AsyncSession,
    ctx: AuthContext,
    conflict_id: uuid.UUID,
    action: str,
    *,
    payload: dict | None = None,
    note: str | None = None,
) -> None:
    db.add(
        BacklinkConflictAction(
            conflict_id=conflict_id,
            workspace_id=ctx.workspace_id,
            action=action,
            payload=payload or {},
            actor_user_id=ctx.user.id,
            note=note,
        )
    )
    await db.flush()


async def list_actions(
    db: AsyncSession, ctx: AuthContext, conflict_id: uuid.UUID
) -> list[dict]:
    """Action history for a conflict — scoped by workspace, and readable even
    after the group itself collapsed (the audit log outlives the group)."""
    rows = (
        await db.execute(
            select(BacklinkConflictAction)
            .where(
                BacklinkConflictAction.conflict_id == conflict_id,
                BacklinkConflictAction.workspace_id == ctx.workspace_id,
            )
            .order_by(BacklinkConflictAction.created_at.desc())
        )
    ).scalars().all()
    return [
        {
            "id": a.id,
            "action": a.action,
            "payload": a.payload or {},
            "actor_user_id": a.actor_user_id,
            "note": a.note,
            "created_at": a.created_at,
        }
        for a in rows
    ]


async def _set_status(
    db: AsyncSession, ctx: AuthContext, conflict: BacklinkConflict, resolution_status: str
) -> None:
    conflict.resolution_status = resolution_status
    if resolution_status in ("resolved", "ignored"):
        conflict.resolved_by = ctx.user.id
        conflict.resolved_at = datetime.now(timezone.utc)
    else:
        conflict.resolved_by = None
        conflict.resolved_at = None


async def resolve(
    db: AsyncSession, ctx: AuthContext, conflict_id: uuid.UUID, resolution_status: str
) -> BacklinkConflict:
    conflict = await db.get(BacklinkConflict, conflict_id)
    if conflict is None or conflict.workspace_id != ctx.workspace_id:
        raise NotFoundError("Conflict not found")
    if resolution_status not in _LIST_STATUSES:
        raise ValidationAppError("Invalid resolution status")
    await _set_status(db, ctx, conflict, resolution_status)
    action = {
        "resolved": "resolve", "ignored": "ignore",
        "acknowledged": "acknowledge", "open": "reopen",
    }.get(resolution_status, "resolve")
    await _record_action(db, ctx, conflict.id, action, payload={"status": resolution_status})
    await db.flush()
    return conflict


async def _members_for_edit(
    db: AsyncSession, ctx: AuthContext, conflict: BacklinkConflict
) -> list[BacklinkRecord]:
    """Load the actual BacklinkRecord rows for a group (workspace-checked)."""
    return list(
        (
            await db.execute(
                select(BacklinkRecord)
                .join(
                    BacklinkConflictMember,
                    BacklinkConflictMember.backlink_id == BacklinkRecord.id,
                )
                .where(
                    BacklinkConflictMember.conflict_id == conflict.id,
                    BacklinkRecord.workspace_id == ctx.workspace_id,
                )
            )
        ).scalars().all()
    )


async def keep_one(
    db: AsyncSession, ctx: AuthContext, conflict_id: uuid.UUID, keep_backlink_id: uuid.UUID
) -> dict:
    """Keep one backlink and delete the OTHER group members.

    Deletion goes through ``backlink_service.delete_backlink`` so issues/history/
    identity stay consistent and the (now sub-2-member) group is dropped. Every
    action is audited. Requires EDIT_BACKLINKS (enforced at the router).
    """
    from app.services import backlink_service, duplicate_service

    conflict, _cu, _fp = await _load_group(db, ctx, conflict_id)
    members = await _members_for_edit(db, ctx, conflict)
    member_ids = {m.id for m in members}
    if keep_backlink_id not in member_ids:
        raise ValidationAppError("keep_backlink_id is not a member of this conflict")

    victims = [m for m in members if m.id != keep_backlink_id]
    dirty_identities: set[uuid.UUID] = set()
    deleted: list[str] = []
    for m in victims:
        ctx.assert_project(m.project_id)  # RBAC: don't let a scoped manager nuke others' rows

    # Log the action WHILE the conflict row still exists — deleting members below
    # prunes the group (member_count < 2) which CASCADE-drops it, so a post-delete
    # insert would violate the FK. Also mirror to the durable workspace audit log.
    await _record_action(
        db, ctx, conflict_id, "keep_one",
        payload={"keep": str(keep_backlink_id), "victims": [str(m.id) for m in victims]},
    )
    from app.models.enums import AuditAction
    from app.services import audit_service

    await audit_service.record(
        db, action=AuditAction.DELETE, actor_user_id=ctx.user.id, workspace_id=ctx.workspace_id,
        entity_type="conflict", entity_id=conflict_id,
        summary=f"Kept 1 of {len(members)} duplicate links; removed {len(victims)}",
    )

    for m in victims:
        if m.link_identity_id:
            dirty_identities.add(m.link_identity_id)
        url = await backlink_service.delete_backlink(db, ctx, m.id)
        deleted.append(url)

    if dirty_identities:
        await duplicate_service.recompute(db, dirty_identities)

    # Re-detect: the group very likely dropped (delete_backlink prunes <2). If the
    # canonical still has >=2 members, refresh it; otherwise it's already gone.
    canonical_id = conflict.canonical_url_id
    if canonical_id is not None:
        await detect_for_canonicals(db, ctx.workspace_id, {canonical_id})
    await db.flush()
    return {"kept": keep_backlink_id, "deleted": deleted, "deleted_count": len(deleted)}


async def reassign(
    db: AsyncSession, ctx: AuthContext, conflict_id: uuid.UUID, to_user_label: str
) -> dict:
    """Set ``assigned_user_label`` on every member, log AssignmentHistory, recompute
    identity. Requires EDIT_BACKLINKS (enforced at the router)."""
    from app.models.link_identity import AssignmentHistory
    from app.services import duplicate_service

    label = (to_user_label or "").strip()
    if not label:
        raise ValidationAppError("to_user_label is required")

    conflict, _cu, _fp = await _load_group(db, ctx, conflict_id)
    members = await _members_for_edit(db, ctx, conflict)
    now = datetime.now(timezone.utc)
    dirty_identities: set[uuid.UUID] = set()
    changed = 0
    for m in members:
        ctx.assert_project(m.project_id)
    for m in members:
        old_label = m.assigned_user_label
        if old_label == label:
            continue
        m.assigned_user_label = label
        m.assigned_at = now
        db.add(
            AssignmentHistory(
                workspace_id=ctx.workspace_id,
                project_id=m.project_id,
                backlink_id=m.id,
                link_identity_id=m.link_identity_id,
                old_user_label=old_label,
                new_user_label=label,
                source="ui",
            )
        )
        if m.link_identity_id:
            dirty_identities.add(m.link_identity_id)
        changed += 1

    await _record_action(
        db, ctx, conflict_id, "reassign",
        payload={"to_user_label": label, "changed": changed},
    )
    if dirty_identities:
        await duplicate_service.recompute(db, dirty_identities)
    # Re-detect: reassignment can flip cross_user → same_project (or vice-versa).
    if conflict.canonical_url_id is not None:
        await detect_for_canonicals(db, ctx.workspace_id, {conflict.canonical_url_id})
    await db.flush()
    return {"to_user_label": label, "changed": changed}


async def bulk_status(
    db: AsyncSession, ctx: AuthContext, conflict_ids: list[uuid.UUID], action: str
) -> dict:
    """Bulk status change (resolve/acknowledge/ignore/reopen) with per-group audit."""
    target = _BULK_ACTIONS.get(action)
    if target is None:
        raise ValidationAppError("action must be resolve|acknowledge|ignore|reopen")
    ids = list({cid for cid in conflict_ids})
    if not ids:
        return {"updated": 0, "action": action}

    clauses = [
        BacklinkConflict.id.in_(ids),
        BacklinkConflict.workspace_id == ctx.workspace_id,
    ]
    rbac = _project_scope_clause(ctx)
    if rbac is not None:
        clauses.append(rbac)
    conflicts = (
        await db.execute(select(BacklinkConflict).where(*clauses))
    ).scalars().all()
    for c in conflicts:
        await _set_status(db, ctx, c, target)
        await _record_action(db, ctx, c.id, action, payload={"status": target, "bulk": True})
    await db.flush()
    return {"updated": len(conflicts), "action": action, "status": target}


async def export_members(db: AsyncSession, ctx: AuthContext, conflict_id: uuid.UUID) -> tuple[list[str], list[list]]:
    """CSV header + rows for every member of a group (RBAC-checked)."""
    conflict, canonical_url, _fp = await _load_group(db, ctx, conflict_id)
    members = (await _members(db, [conflict.id])).get(conflict.id, [])
    headers = [
        "backlink_id", "project", "source_page_url", "target_url",
        "target_domain", "anchor", "rel", "assigned_user", "link_type",
        "status", "score", "index_status", "duplicate_status",
        "placement_date", "created_at", "last_checked_at",
    ]
    rows: list[list] = []
    for m in members:
        anchor = _coalesce(m.get("current_anchor_text"), m.get("expected_anchor_text"))
        rel = _coalesce(m.get("current_rel"), m.get("expected_rel"))
        rows.append(
            [
                str(m.get("backlink_id") or ""),
                m.get("project_name") or "",
                m.get("source_page_url") or "",
                m.get("target_url") or "",
                m.get("target_domain") or "",
                anchor or "",
                rel or "",
                m.get("assigned_user_label") or "",
                m.get("link_type") or "",
                m.get("status") or "",
                m.get("score") if m.get("score") is not None else "",
                m.get("index_status") or "",
                m.get("duplicate_status") or "",
                m.get("placement_date").isoformat() if m.get("placement_date") else "",
                m.get("created_at").isoformat() if m.get("created_at") else "",
                m.get("last_checked_at").isoformat() if m.get("last_checked_at") else "",
            ]
        )
    return headers, rows
