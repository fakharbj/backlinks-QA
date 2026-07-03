"""User performance analytics (Phase 9 P1).

Per-user stats over a timeframe, with the owner-defined "new source domain"
rules computed from data (retroactive, no import-path coupling):

* **project-new** — the FIRST backlink ever from that source domain *within that
  project* (the domain may already exist globally; owners' example.com rule).
* **global-new** — the first backlink ever from that domain across the workspace.

A row is "new" when the first-ever occurrence falls inside the window, so the
numbers are stable and re-computable for any past period. ``compare=True`` runs
the same query for the previous window of equal length and reports both.
"""

from __future__ import annotations

import uuid
from datetime import datetime, timedelta, timezone

from sqlalchemy import bindparam, text
from sqlalchemy.dialects.postgresql import ARRAY
from sqlalchemy.dialects.postgresql import UUID as PGUUID
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.deps import AuthContext

_EFF = "coalesce(b.override_status, b.status)"


def _scope(ctx: AuthContext, project_id: uuid.UUID | None) -> tuple[str, dict]:
    clause = "b.workspace_id = :ws"
    params: dict = {"ws": ctx.workspace_id}
    if project_id is not None:
        ctx.assert_project(project_id)
        clause += " AND b.project_id = :pid"
        params["pid"] = project_id
    elif ctx.allowed_project_ids is not None:
        clause += " AND b.project_id = ANY(:pids)"
        params["pids"] = list(ctx.allowed_project_ids) or [uuid.uuid4()]
    return clause, params


def _bind(sql: str, params: dict):
    t = text(sql)
    if "pids" in params:
        t = t.bindparams(bindparam("pids", type_=ARRAY(PGUUID(as_uuid=True))))
    return t


async def _window(
    db: AsyncSession,
    ctx: AuthContext,
    t0: datetime,
    t1: datetime,
    project_id: uuid.UUID | None,
) -> list[dict]:
    where, params = _scope(ctx, project_id)
    params |= {"t0": t0, "t1": t1}
    # "first ever" checks compare against ALL earlier rows (any time), so a domain
    # only counts as new on its true first appearance.
    sql = _bind(
        f"""
        SELECT coalesce(nullif(b.assigned_user_label, ''), '(unassigned)') AS user_label,
               count(*)                                                    AS links,
               count(*) FILTER (WHERE b.index_status = 'indexed')          AS indexed,
               count(*) FILTER (WHERE {_EFF} = 'PASS')                     AS pass,
               count(*) FILTER (WHERE {_EFF} = 'FAIL')                     AS fail,
               count(*) FILTER (WHERE b.is_duplicate IS TRUE)              AS duplicates,
               round(avg(b.score) FILTER (WHERE b.score IS NOT NULL), 1)   AS avg_score,
               count(*) FILTER (WHERE b.source_domain IS NOT NULL AND NOT EXISTS (
                   SELECT 1 FROM backlink_records e
                   WHERE e.project_id = b.project_id AND e.source_domain = b.source_domain
                     AND e.created_at < b.created_at
               ))                                                          AS project_new_domains,
               count(*) FILTER (WHERE b.source_domain IS NOT NULL AND NOT EXISTS (
                   SELECT 1 FROM backlink_records e
                   WHERE e.workspace_id = b.workspace_id AND e.source_domain = b.source_domain
                     AND e.created_at < b.created_at
               ))                                                          AS global_new_domains
        FROM backlink_records b
        WHERE {where} AND b.created_at >= :t0 AND b.created_at < :t1
        GROUP BY 1
        ORDER BY links DESC
        """,
        params,
    )
    rows = (await db.execute(sql, params)).mappings().all()
    return [dict(r) for r in rows]


async def users(
    db: AsyncSession,
    ctx: AuthContext,
    *,
    days: int = 30,
    date_from: datetime | None = None,
    date_to: datetime | None = None,
    project_id: uuid.UUID | None = None,
    compare: bool = True,
    compare_from: datetime | None = None,
    compare_to: datetime | None = None,
) -> dict:
    """Per-user performance for a window (default: last N days) with an optional
    comparison window — the previous equal-length period by default, or any
    custom period via ``compare_from``/``compare_to``."""
    t1 = date_to or datetime.now(timezone.utc)
    t0 = date_from or (t1 - timedelta(days=max(1, min(days, 3660))))
    span = t1 - t0

    current = await _window(db, ctx, t0, t1, project_id)
    previous: dict[str, dict] = {}
    c1 = compare_to or t0
    c0 = compare_from or (c1 - span)
    if compare:
        prev_rows = await _window(db, ctx, c0, c1, project_id)
        previous = {r["user_label"]: r for r in prev_rows}

    # TeamLead scoping: managers with member assignments only see their people.
    from app.services.workforce_service import visible_labels

    scope = await visible_labels(db, ctx)
    if scope is not None:
        current = [r for r in current if r["user_label"] in scope]
        previous = {k: v for k, v in previous.items() if k in scope}

    out = []
    for r in current:
        prev = previous.get(r["user_label"])
        out.append({**r, "previous": prev})
    # Users active in the previous window but idle now still matter for review.
    for label, prev in previous.items():
        if not any(r["user_label"] == label for r in current):
            out.append(
                {
                    "user_label": label, "links": 0, "indexed": 0, "pass": 0, "fail": 0,
                    "duplicates": 0, "avg_score": None, "project_new_domains": 0,
                    "global_new_domains": 0, "previous": prev,
                }
            )
    # GSC-style weekly series over the same window (links / new domains / indexed).
    where, wparams = _scope(ctx, project_id)
    wparams |= {"t0": t0, "t1": t1}
    weekly_sql = _bind(
        f"""
        SELECT to_char(date_trunc('week', b.created_at), 'YYYY-MM-DD') AS week,
               count(*) AS links,
               count(*) FILTER (WHERE b.index_status = 'indexed') AS indexed,
               count(*) FILTER (WHERE b.source_domain IS NOT NULL AND NOT EXISTS (
                   SELECT 1 FROM backlink_records e
                   WHERE e.project_id = b.project_id AND e.source_domain = b.source_domain
                     AND e.created_at < b.created_at
               )) AS new_domains
        FROM backlink_records b
        WHERE {where} AND b.created_at >= :t0 AND b.created_at < :t1
        GROUP BY 1 ORDER BY 1 ASC
        """,
        wparams,
    )
    weekly = [dict(r) for r in (await db.execute(weekly_sql, wparams)).mappings().all()]

    return {
        "from": t0.isoformat(),
        "to": t1.isoformat(),
        "compared_to_previous": compare,
        "compare_from": c0.isoformat() if compare else None,
        "compare_to": c1.isoformat() if compare else None,
        "users": out,
        "weekly": weekly,
    }
