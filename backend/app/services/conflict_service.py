"""Backlink conflict (duplicate) detection + resolution (Phase 8, feature 9).

A conflict groups backlinks that share the same canonical source URL
(``canonical_url_id``) within a workspace. ``classify_scope`` is a pure rule
(unit-tested). ``rebuild_workspace`` recomputes every group from current data
(preserving prior resolution decisions); ``resolve`` records the review outcome.

Detection keys off the indexed ``canonical_url_id``, so it scales without scanning
the backlink table.
"""

from __future__ import annotations

import uuid
from datetime import datetime, timezone

from sqlalchemy import String, cast, delete, func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.deps import AuthContext
from app.core.errors import NotFoundError
from app.models.backlink import BacklinkRecord
from app.models.canonical_url import CanonicalUrl
from app.models.conflict import BacklinkConflict, BacklinkConflictMember
from app.models.project import Project

SAME_PROJECT = "same_project"
CROSS_PROJECT = "cross_project"
CROSS_USER = "cross_user"

_KEEP_STATUSES = ("acknowledged", "resolved", "ignored")


def classify_scope(project_count: int, user_count: int) -> str:
    """Pure rule (unit-tested): spanning projects > spanning users > same project."""
    if project_count > 1:
        return CROSS_PROJECT
    if user_count > 1:
        return CROSS_USER
    return SAME_PROJECT


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
        changed += 1
    await db.flush()
    return changed


async def summary(db: AsyncSession, ctx: AuthContext) -> dict:
    rows = (
        await db.execute(
            select(
                BacklinkConflict.resolution_status,
                BacklinkConflict.scope,
                func.count(),
            )
            .where(BacklinkConflict.workspace_id == ctx.workspace_id)
            .group_by(BacklinkConflict.resolution_status, BacklinkConflict.scope)
        )
    ).all()
    total = open_ = resolved = 0
    by_scope: dict[str, int] = {}
    for status, scope, n in rows:
        total += n
        if status == "open":
            open_ += n
        if status == "resolved":
            resolved += n
        by_scope[scope] = by_scope.get(scope, 0) + n

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
        "by_scope": by_scope, "weekly": weekly,
    }


async def list_conflicts(
    db: AsyncSession, ctx: AuthContext, *, status: str | None = None, limit: int = 200
) -> list[dict]:
    stmt = (
        select(BacklinkConflict, CanonicalUrl.canonical_url, CanonicalUrl.fingerprint)
        .outerjoin(CanonicalUrl, CanonicalUrl.id == BacklinkConflict.canonical_url_id)
        .where(BacklinkConflict.workspace_id == ctx.workspace_id)
    )
    if status:
        stmt = stmt.where(BacklinkConflict.resolution_status == status)
    # Project-scoped principals only see groups confined to their projects.
    if ctx.allowed_project_ids is not None:
        stmt = stmt.where(
            BacklinkConflict.project_id.in_(ctx.allowed_project_ids or {uuid.uuid4()})
        )
    stmt = stmt.order_by(
        BacklinkConflict.member_count.desc(), BacklinkConflict.detected_at.desc()
    ).limit(limit)

    rows = (await db.execute(stmt)).all()
    members_by_conflict = await _members(db, [c.id for c, _u, _f in rows])

    out: list[dict] = []
    for conflict, canonical_url, fingerprint in rows:
        out.append(
            {
                "id": conflict.id,
                "canonical_url": canonical_url,
                "fingerprint": fingerprint,
                "project_id": conflict.project_id,
                "scope": conflict.scope,
                "resolution_status": conflict.resolution_status,
                "member_count": conflict.member_count,
                "detected_at": conflict.detected_at,
                "created_at": conflict.created_at,
                "members": members_by_conflict.get(conflict.id, []),
            }
        )
    return out


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
            )
            .join(BacklinkRecord, BacklinkRecord.id == BacklinkConflictMember.backlink_id)
            .outerjoin(Project, Project.id == BacklinkRecord.project_id)
            .where(BacklinkConflictMember.conflict_id.in_(conflict_ids))
        )
    ).all()
    out: dict[uuid.UUID, list[dict]] = {}
    for cid, bid, pid, pname, src, tgt, status, score, label, link_type in rows:
        out.setdefault(cid, []).append(
            {
                "backlink_id": bid,
                "project_id": pid,
                "project_name": pname,
                "source_page_url": src,
                "target_url": tgt,
                "status": status.value if status is not None else None,
                "score": score,
                "assigned_user_label": label,
                "link_type": link_type,
            }
        )
    return out


async def resolve(
    db: AsyncSession, ctx: AuthContext, conflict_id: uuid.UUID, resolution_status: str
) -> BacklinkConflict:
    conflict = await db.get(BacklinkConflict, conflict_id)
    if conflict is None or conflict.workspace_id != ctx.workspace_id:
        raise NotFoundError("Conflict not found")
    conflict.resolution_status = resolution_status
    if resolution_status in ("resolved", "ignored"):
        conflict.resolved_by = ctx.user.id
        conflict.resolved_at = datetime.now(timezone.utc)
    else:
        conflict.resolved_by = None
        conflict.resolved_at = None
    await db.flush()
    return conflict
