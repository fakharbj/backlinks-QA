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

from sqlalchemy import bindparam, func, text
from sqlalchemy.dialects.postgresql import ARRAY
from sqlalchemy.dialects.postgresql import UUID as PGUUID
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.deps import AuthContext

_EFF = "coalesce(b.override_status, b.status)"

# The link's REAL creation/placement day — the date the backlink went live, as
# supplied in the Google Sheet (``placement_date``). Performance, task-completion,
# "new domain first-seen" and duplicate timing all attribute a link to THIS day,
# NOT to ``created_at`` (which is merely when the row was imported). Falls back to
# the import time only when the sheet gave no date, so no rows silently drop.
_LINK_TS = "coalesce(b.placement_date, b.created_at)"       # timestamptz (window filters)
_LINK_TS_E = "coalesce(e.placement_date, e.created_at)"     # same, for the "first ever" subquery
_LINK_DAY_RAW = "coalesce(placement_date, created_at::date)"  # ::date (actuals CTEs, no alias)


def completion_cutoff() -> "date | None":
    """Owner rule: task-completion metrics start fresh at
    ``TASK_COMPLETION_START_DATE`` — assignments planned before it are ignored
    by every completion aggregate (plan stats, weekly target-vs-done, project
    effort). Returns None when the knob is empty/invalid (no cutoff)."""
    from datetime import date as _date

    from app.core.config import settings as _settings

    raw = (_settings.TASK_COMPLETION_START_DATE or "").strip()
    if not raw:
        return None
    try:
        return _date.fromisoformat(raw)
    except ValueError:
        return None


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
                     AND ({_LINK_TS_E}, e.id) < ({_LINK_TS}, b.id)
               ))                                                          AS project_new_domains,
               count(*) FILTER (WHERE b.source_domain IS NOT NULL AND NOT EXISTS (
                   SELECT 1 FROM backlink_records e
                   WHERE e.workspace_id = b.workspace_id AND e.source_domain = b.source_domain
                     AND ({_LINK_TS_E}, e.id) < ({_LINK_TS}, b.id)
               ))                                                          AS global_new_domains
        FROM backlink_records b
        WHERE {where} AND {_LINK_TS} >= :t0 AND {_LINK_TS} < :t1
        GROUP BY 1
        ORDER BY links DESC
        """,
        params,
    )
    rows = (await db.execute(sql, params)).mappings().all()
    return [dict(r) for r in rows]


async def user_dashboard(
    db: AsyncSession,
    ctx: AuthContext,
    *,
    user_label: str,
    days: int = 30,
    date_from: datetime | None = None,
    date_to: datetime | None = None,
    project_id: uuid.UUID | None = None,
    link_type: str | None = None,
    date_type: str = "created",
    compare: bool = True,
    granularity: str = "week",
) -> dict:
    """Everything an admin needs about ONE person in a single payload: hours &
    plan completion (excusal-aware, any window length), link production +
    quality (full KPI vocabulary + HTTP buckets), per-project + per-link-type
    breakdowns, weekly trends, a team-benchmark strip, rates, leave history —
    plus the previous equal-length window for comparison.

    ``date_type`` chooses which link date the window filters on (created /
    QA-checked / sheet-created); plan & leave always use calendar days."""
    t1 = date_to or datetime.now(timezone.utc)
    t0 = date_from or (t1 - timedelta(days=max(1, min(days, 3660))))
    span = t1 - t0

    # Whitelisted date column for the link window — never interpolate raw input.
    # "created" is the REAL backlink creation/placement day (sheet-supplied), which
    # is the default and what performance is measured on; "imported" is the raw
    # upload time; "checked"/"sheet" expose the other axes.
    _DATE_COL = {
        "created": _LINK_TS,
        "imported": "b.created_at",
        "checked": "b.last_checked_at",
        "sheet": "b.sheet_created_date",
    }
    dcol = _DATE_COL.get(date_type, _LINK_TS)
    # Chart bucket — whitelisted from a fixed set; interpolated into date_trunc,
    # never bound (the :param::type cast gotcha). Default 'week'.
    bucket = granularity if granularity in ("day", "week", "month") else "week"

    where, params = _scope(ctx, project_id)
    params |= {"label": user_label}

    lt_clause = ""
    if link_type:
        lt_clause = " AND b.link_type = :lt"
        params["lt"] = link_type

    async def _link_stats(a: datetime, b: datetime) -> dict:
        p = dict(params) | {"t0": a, "t1": b}
        # Full analytics KPI vocabulary so the dashboard row matches AnalyticsDesk.
        sql = _bind(
            f"""
            SELECT count(*) AS links,
                   count(*) FILTER (WHERE b.index_status = 'indexed')        AS indexed,
                   count(*) FILTER (WHERE b.index_status = 'not_indexed')    AS not_indexed,
                   count(*) FILTER (WHERE b.index_status IS NULL)            AS index_unchecked,
                   count(*) FILTER (WHERE {_EFF} = 'FAIL')                   AS fail,
                   count(*) FILTER (WHERE {_EFF} = 'PASS')                   AS pass,
                   count(*) FILTER (WHERE {_EFF} = 'WARNING')                AS warning,
                   count(*) FILTER (WHERE {_EFF} = 'UNKNOWN')                AS unknown,
                   count(*) FILTER (WHERE {_EFF} = 'NEEDS_MANUAL_REVIEW')    AS review,
                   count(*) FILTER (WHERE {_EFF} = 'PENDING')                AS qa_pending,
                   count(*) FILTER (WHERE b.is_duplicate IS TRUE)            AS duplicates,
                   count(*) FILTER (WHERE b.link_found IS FALSE)             AS link_missing,
                   count(*) FILTER (WHERE b.current_rel = 'nofollow')        AS nofollow,
                   count(*) FILTER (WHERE b.current_rel = 'dofollow')        AS dofollow,
                   count(*) FILTER (WHERE b.http_status BETWEEN 200 AND 299) AS http_2xx,
                   count(*) FILTER (WHERE b.http_status BETWEEN 300 AND 399) AS http_3xx,
                   count(*) FILTER (WHERE b.http_status BETWEEN 400 AND 499) AS http_4xx,
                   count(*) FILTER (WHERE b.http_status BETWEEN 500 AND 599) AS http_5xx,
                   round(avg(b.score) FILTER (WHERE b.score IS NOT NULL), 1) AS avg_score,
                   count(*) FILTER (WHERE b.source_domain IS NOT NULL AND NOT EXISTS (
                       SELECT 1 FROM backlink_records e
                       WHERE e.project_id = b.project_id AND e.source_domain = b.source_domain
                         AND ({_LINK_TS_E}, e.id) < ({_LINK_TS}, b.id)))                     AS project_new_domains,
                   count(*) FILTER (WHERE b.source_domain IS NOT NULL AND NOT EXISTS (
                       SELECT 1 FROM backlink_records e
                       WHERE e.workspace_id = b.workspace_id AND e.source_domain = b.source_domain
                         AND ({_LINK_TS_E}, e.id) < ({_LINK_TS}, b.id)))                     AS global_new_domains
            FROM backlink_records b
            WHERE {where} AND lower(b.assigned_user_label) = lower(:label)
              AND {dcol} >= :t0 AND {dcol} < :t1{lt_clause}
            """,
            p,
        )
        row = (await db.execute(sql, p)).mappings().first() or {}
        out = {k: (float(v) if k == "avg_score" and v is not None else (int(v) if v is not None else (None if k == "avg_score" else 0))) for k, v in dict(row).items()}
        # Derived rates (guard divide-by-zero → None renders as "—").
        out["qualified_rate"] = round(100.0 * out["pass"] / out["links"], 1) if out.get("links") else None
        idx_base = out["indexed"] + out["not_indexed"]
        out["indexed_rate"] = round(100.0 * out["indexed"] / idx_base, 1) if idx_base else None
        return out

    # Plan vs done — excusal-aware in SQL so ANY window length works (the
    # interactive day-report is capped at 92 days).
    async def _plan_stats(a: datetime, b: datetime) -> dict:
        cut = completion_cutoff()
        p = {
            "ws": ctx.workspace_id, "label": user_label,
            "f": a.date(), "t": b.date(),
            # Completion clock starts at the owner cutoff — earlier plans are
            # ignored by the METRICS (planner views still show them).
            "pf": max(a.date(), cut) if cut else a.date(),
        }
        proj_clause = ""
        if project_id is not None:
            proj_clause = " AND a.project_id = :pid"
            p["pid"] = project_id
        sql = text(
            f"""
            WITH actuals AS (
                SELECT project_id, lower(assigned_user_label) AS u,
                       {_LINK_DAY_RAW} AS d, count(*) AS n
                FROM backlink_records
                WHERE workspace_id = :ws
                  AND coalesce(placement_date, created_at) >= :f
                  AND coalesce(placement_date, created_at) < CAST(:t AS date) + INTERVAL '1 day'
                  AND lower(assigned_user_label) = lower(:label)
                GROUP BY 1, 2, 3
            ),
            plan AS (
                SELECT a.id, a.project_id, a.day, a.hours, a.expected_links,
                       coalesce(act.n, 0) AS done,
                       (
                         coalesce(w.is_working, extract(dow FROM a.day) <> 0)
                         IS DISTINCT FROM TRUE
                         OR EXISTS (
                           SELECT 1 FROM leave_requests lv
                           WHERE lv.workspace_id = a.workspace_id AND lv.status = 'approved'
                             AND lower(lv.user_label) = lower(a.user_label)
                             AND lv.start_date <= a.day AND lv.end_date >= a.day)
                       ) AS excused
                FROM task_assignments a
                LEFT JOIN working_days w
                  ON w.workspace_id = a.workspace_id AND w.day = a.day
                LEFT JOIN actuals act
                  ON act.project_id = a.project_id AND act.d = a.day
                 AND act.u = lower(a.user_label)
                WHERE a.workspace_id = :ws AND lower(a.user_label) = lower(:label)
                  AND a.day >= :pf AND a.day <= :t{proj_clause}
            )
            SELECT count(*)                                            AS assignments,
                   coalesce(sum(hours), 0)                             AS hours_assigned,
                   coalesce(sum(hours) FILTER (WHERE NOT excused), 0)  AS hours_counted,
                   coalesce(sum(expected_links) FILTER (WHERE NOT excused), 0) AS target,
                   coalesce(sum(done) FILTER (WHERE NOT excused), 0)   AS done,
                   count(*) FILTER (WHERE excused)                     AS excused_days
            FROM plan
            """
        )
        row = (await db.execute(sql, p)).mappings().first() or {}
        out = {k: float(v) if k in ("hours_assigned", "hours_counted") else int(v or 0) for k, v in dict(row).items()}
        out["completion_pct"] = (
            round(100.0 * out["done"] / out["target"], 1) if out.get("target") else None
        )
        return out

    current_links = await _link_stats(t0, t1)
    current_plan = await _plan_stats(t0, t1)
    previous = None
    if compare:
        previous = {
            "links": await _link_stats(t0 - span, t0),
            "plan": await _plan_stats(t0 - span, t0),
        }

    # Per-project breakdown (links + plan) for the current window.
    p2 = dict(params) | {"t0": t0, "t1": t1}
    proj_sql = _bind(
        f"""
        SELECT b.project_id, count(*) AS links,
               count(*) FILTER (WHERE b.index_status = 'indexed') AS indexed,
               count(*) FILTER (WHERE {_EFF} = 'FAIL')            AS fail,
               count(*) FILTER (WHERE b.source_domain IS NOT NULL AND NOT EXISTS (
                   SELECT 1 FROM backlink_records e
                   WHERE e.project_id = b.project_id AND e.source_domain = b.source_domain
                     AND ({_LINK_TS_E}, e.id) < ({_LINK_TS}, b.id)))              AS project_new_domains
        FROM backlink_records b
        WHERE {where} AND lower(b.assigned_user_label) = lower(:label)
          AND {dcol} >= :t0 AND {dcol} < :t1{lt_clause}
        GROUP BY 1 ORDER BY 2 DESC
        """,
        p2,
    )
    by_project = {str(r["project_id"]): dict(r) for r in (await db.execute(proj_sql, p2)).mappings().all()}
    plan_proj_sql = text(
        """
        SELECT a.project_id, coalesce(sum(a.hours), 0) AS hours,
               coalesce(sum(a.expected_links), 0) AS target
        FROM task_assignments a
        WHERE a.workspace_id = :ws AND lower(a.user_label) = lower(:label)
          AND a.day >= :f AND a.day <= :t
        GROUP BY 1
        """
    )
    _cut = completion_cutoff()
    for r in (
        await db.execute(
            plan_proj_sql,
            {"ws": ctx.workspace_id, "label": user_label,
             "f": max(t0.date(), _cut) if _cut else t0.date(), "t": t1.date()},
        )
    ).mappings().all():
        key = str(r["project_id"])
        entry = by_project.setdefault(key, {"project_id": r["project_id"], "links": 0, "indexed": 0, "fail": 0, "project_new_domains": 0})
        entry["hours"] = float(r["hours"])
        entry["target"] = int(r["target"])
    projects_out = []
    for key, v in by_project.items():
        v["project_id"] = key
        v.setdefault("hours", 0.0)
        v.setdefault("target", 0)
        projects_out.append({k: (float(x) if k == "hours" else (str(x) if k == "project_id" else int(x))) for k, x in v.items()})
    projects_out.sort(key=lambda r: (-r["links"], -r["hours"]))

    # Weekly series (links / new domains / indexed / qualified / not qualified) + plan trend.
    wk_sql = _bind(
        f"""
        SELECT to_char(date_trunc('{bucket}', {dcol}), 'YYYY-MM-DD') AS week,
               count(*) AS links,
               count(*) FILTER (WHERE b.index_status = 'indexed') AS indexed,
               count(*) FILTER (WHERE {_EFF} = 'PASS')            AS pass,
               count(*) FILTER (WHERE {_EFF} = 'FAIL')            AS fail,
               count(*) FILTER (WHERE b.source_domain IS NOT NULL AND NOT EXISTS (
                   SELECT 1 FROM backlink_records e
                   WHERE e.project_id = b.project_id AND e.source_domain = b.source_domain
                     AND ({_LINK_TS_E}, e.id) < ({_LINK_TS}, b.id)))              AS new_domains
        FROM backlink_records b
        WHERE {where} AND lower(b.assigned_user_label) = lower(:label)
          AND {dcol} >= :t0 AND {dcol} < :t1{lt_clause}
        GROUP BY 1 ORDER BY 1
        """,
        p2,
    )
    weekly = [dict(r) for r in (await db.execute(wk_sql, p2)).mappings().all()]

    # Per-link-type distribution for THIS user (mirrors project_effort.by_type).
    type_sql = _bind(
        f"""
        SELECT coalesce(nullif(b.link_type, ''), '(none)') AS link_type,
               count(*) AS links,
               count(*) FILTER (WHERE {_EFF} = 'PASS')            AS pass,
               count(*) FILTER (WHERE b.index_status = 'indexed') AS indexed
        FROM backlink_records b
        WHERE {where} AND lower(b.assigned_user_label) = lower(:label)
          AND {dcol} >= :t0 AND {dcol} < :t1{lt_clause}
        GROUP BY 1 ORDER BY 2 DESC
        """,
        p2,
    )
    by_type = [dict(r) for r in (await db.execute(type_sql, p2)).mappings().all()]

    plan_wk_sql = text(
        f"""
        WITH actuals AS (
            SELECT project_id, coalesce(placement_date, created_at::date) AS d, count(*) AS n
            FROM backlink_records
            WHERE workspace_id = :ws AND lower(assigned_user_label) = lower(:label)
              AND coalesce(placement_date, created_at) >= :f
              AND coalesce(placement_date, created_at) < CAST(:t AS date) + INTERVAL '1 day'
            GROUP BY 1, 2
        )
        SELECT to_char(date_trunc('{bucket}', a.day), 'YYYY-MM-DD') AS week,
               coalesce(sum(a.expected_links), 0) AS target,
               coalesce(sum(act.n), 0)            AS done
        FROM task_assignments a
        LEFT JOIN actuals act ON act.project_id = a.project_id AND act.d = a.day
        WHERE a.workspace_id = :ws AND lower(a.user_label) = lower(:label)
          AND a.day >= :pf AND a.day <= :t
        GROUP BY 1 ORDER BY 1
        """
    )
    plan_weekly = [
        dict(r)
        for r in (
            await db.execute(
                plan_wk_sql,
                {"ws": ctx.workspace_id, "label": user_label, "f": t0.date(), "t": t1.date(),
                 "pf": max(t0.date(), _cut) if _cut else t0.date()},
            )
        ).mappings().all()
    ]

    # Rates in effect + leave history.
    from app.models.workforce import LeaveRequest, LinkTypeProductivity, UserProductivityOverride
    from sqlalchemy import select

    rates_global = [
        {"link_type_name": r.link_type_name, "links_per_hour": float(r.links_per_hour)}
        for r in (
            await db.execute(
                select(LinkTypeProductivity)
                .where(LinkTypeProductivity.workspace_id == ctx.workspace_id)
                .order_by(LinkTypeProductivity.link_type_name)
            )
        ).scalars().all()
    ]
    rates_override = [
        {"link_type_name": r.link_type_name, "links_per_hour": float(r.links_per_hour)}
        for r in (
            await db.execute(
                select(UserProductivityOverride).where(
                    UserProductivityOverride.workspace_id == ctx.workspace_id,
                    func.lower(UserProductivityOverride.user_label) == user_label.lower(),
                )
            )
        ).scalars().all()
    ]
    leaves = [
        {
            "id": str(l.id), "start_date": l.start_date.isoformat(),
            "end_date": l.end_date.isoformat(), "reason": l.reason, "status": l.status,
        }
        for l in (
            await db.execute(
                select(LeaveRequest)
                .where(
                    LeaveRequest.workspace_id == ctx.workspace_id,
                    func.lower(LeaveRequest.user_label) == user_label.lower(),
                )
                .order_by(LeaveRequest.start_date.desc())
                .limit(50)
            )
        ).scalars().all()
    ]

    # Team benchmark — reuse the tenant + TeamLead-scoped peer query (visible_labels
    # already applied inside users()), then rank this person and average the peers.
    team = None
    try:
        peers = (await users(db, ctx, days=days, date_from=t0, date_to=t1,
                             project_id=project_id, compare=False))["users"]
    except Exception:  # noqa: BLE001 — benchmark is best-effort, never blocks the dashboard
        peers = []
    ranked = [pr for pr in peers if pr.get("user_label") != "(unassigned)"]
    if ranked:
        ranked_sorted = sorted(ranked, key=lambda r: r.get("links") or 0, reverse=True)
        of = len(ranked_sorted)
        me = next((i for i, r in enumerate(ranked_sorted)
                   if (r.get("user_label") or "").lower() == user_label.lower()), None)
        n = of or 1
        avg_links = round(sum((r.get("links") or 0) for r in ranked_sorted) / n, 1)
        avg_indexed = round(sum((r.get("indexed") or 0) for r in ranked_sorted) / n, 1)
        scored = [r.get("avg_score") for r in ranked_sorted if r.get("avg_score") is not None]
        rates = [
            (100.0 * (r.get("pass") or 0) / r["links"]) for r in ranked_sorted if r.get("links")
        ]
        team = {
            "rank": (me + 1) if me is not None else None,
            "of": of,
            "avg_links": avg_links,
            "avg_indexed": avg_indexed,
            "avg_score": round(sum(scored) / len(scored), 1) if scored else None,
            "avg_qualified_rate": round(sum(rates) / len(rates), 1) if rates else None,
            "top_links": ranked_sorted[0].get("links") or 0,
            "this_user_links": current_links.get("links", 0),
            # Full per-member distribution (capped) so the UI can show everyone —
            # not just the average — with this person highlighted. Enables a
            # flexible, interactive benchmark chart across several metrics.
            "members": [
                {
                    "user_label": r.get("user_label"),
                    "links": r.get("links") or 0,
                    "indexed": r.get("indexed") or 0,
                    "avg_score": r.get("avg_score"),
                    "qualified_rate": (
                        round(100.0 * (r.get("pass") or 0) / r["links"], 1) if r.get("links") else 0.0
                    ),
                    "is_current": (r.get("user_label") or "").lower() == user_label.lower(),
                }
                for r in ranked_sorted[:50]
            ],
        }

    return {
        "user_label": user_label,
        "from": t0.isoformat(),
        "to": t1.isoformat(),
        "date_type": date_type,
        "links": current_links,
        "plan": current_plan,
        "previous": previous,
        "projects": projects_out,
        "by_type": by_type,
        "team": team,
        "weekly": weekly,
        "plan_weekly": plan_weekly,
        "rates": {"global": rates_global, "overrides": rates_override},
        "leaves": leaves,
    }


async def project_effort(
    db: AsyncSession,
    ctx: AuthContext,
    *,
    project_id: uuid.UUID,
    days: int = 30,
    date_from: datetime | None = None,
    date_to: datetime | None = None,
    user_label: str | None = None,
    link_type: str | None = None,
    granularity: str = "week",
) -> dict:
    """Project-effort rollup: who worked how much on THIS project, target vs
    done, quality split per person, link-type distribution and a weekly trend."""
    ctx.assert_project(project_id)
    t1 = date_to or datetime.now(timezone.utc)
    t0 = date_from or (t1 - timedelta(days=max(1, min(days, 3660))))
    bucket = granularity if granularity in ("day", "week", "month") else "week"

    _cut = completion_cutoff()
    p: dict = {"ws": ctx.workspace_id, "pid": project_id, "t0": t0, "t1": t1,
               "f": t0.date(), "t": t1.date(),
               # Plan/target CTEs start at the completion cutoff (owner rule);
               # link production (:t0/:f on backlink CTEs) is NOT clamped.
               "pf": max(t0.date(), _cut) if _cut else t0.date()}
    user_clause_b = user_clause_a = ""
    if user_label:
        user_clause_b = " AND lower(b.assigned_user_label) = lower(:label)"
        user_clause_a = " AND lower(a.user_label) = lower(:label)"
        p["label"] = user_label
    lt_clause = ""
    if link_type:
        lt_clause = " AND b.link_type = :lt"
        p["lt"] = link_type

    users_sql = text(
        f"""
        WITH links AS (
            SELECT lower(coalesce(nullif(b.assigned_user_label, ''), '(unassigned)')) AS u,
                   min(coalesce(nullif(b.assigned_user_label, ''), '(unassigned)'))   AS label,
                   count(*) AS links,
                   count(*) FILTER (WHERE b.index_status = 'indexed')       AS indexed,
                   count(*) FILTER (WHERE {_EFF} = 'FAIL')                  AS fail,
                   count(*) FILTER (WHERE {_EFF} = 'PENDING')               AS qa_pending,
                   count(*) FILTER (WHERE b.is_duplicate IS TRUE)           AS duplicates
            FROM backlink_records b
            WHERE b.workspace_id = :ws AND b.project_id = :pid
              AND {_LINK_TS} >= :t0 AND {_LINK_TS} < :t1{user_clause_b}{lt_clause}
            GROUP BY 1
        ),
        plan AS (
            SELECT lower(a.user_label) AS u, min(a.user_label) AS label,
                   coalesce(sum(a.hours), 0) AS hours,
                   coalesce(sum(a.expected_links), 0) AS target
            FROM task_assignments a
            WHERE a.workspace_id = :ws AND a.project_id = :pid
              AND a.day >= :pf AND a.day <= :t{user_clause_a}
            GROUP BY 1
        )
        SELECT coalesce(links.u, plan.u) AS u,
               coalesce(links.label, plan.label) AS label,
               coalesce(links.links, 0) AS links,
               coalesce(links.indexed, 0) AS indexed,
               coalesce(links.fail, 0) AS fail,
               coalesce(links.qa_pending, 0) AS qa_pending,
               coalesce(links.duplicates, 0) AS duplicates,
               coalesce(plan.hours, 0) AS hours,
               coalesce(plan.target, 0) AS target
        FROM links FULL OUTER JOIN plan USING (u)
        ORDER BY 3 DESC, 8 DESC
        """
    )
    users_rows = []
    totals = {"hours": 0.0, "target": 0, "links": 0, "indexed": 0, "fail": 0, "qa_pending": 0, "duplicates": 0}
    for r in (await db.execute(users_sql, p)).mappings().all():
        row = {
            "user_label": r["label"], "links": int(r["links"]), "indexed": int(r["indexed"]),
            "fail": int(r["fail"]), "qa_pending": int(r["qa_pending"]),
            "duplicates": int(r["duplicates"]), "hours": float(r["hours"]),
            "target": int(r["target"]),
        }
        row["completion_pct"] = round(100.0 * row["links"] / row["target"], 1) if row["target"] else None
        users_rows.append(row)
        totals["hours"] += row["hours"]
        for k in ("target", "links", "indexed", "fail", "qa_pending", "duplicates"):
            totals[k] += row[k]
    totals["hours"] = round(totals["hours"], 1)
    totals["completion_pct"] = (
        round(100.0 * totals["links"] / totals["target"], 1) if totals["target"] else None
    )

    type_sql = text(
        f"""
        SELECT coalesce(nullif(b.link_type, ''), '(none)') AS link_type, count(*) AS links
        FROM backlink_records b
        WHERE b.workspace_id = :ws AND b.project_id = :pid
          AND {_LINK_TS} >= :t0 AND {_LINK_TS} < :t1{user_clause_b}
        GROUP BY 1 ORDER BY 2 DESC
        """
    )
    by_type = [dict(r) for r in (await db.execute(type_sql, p)).mappings().all()]

    trend_sql = text(
        f"""
        WITH actuals AS (
            SELECT to_char(date_trunc('{bucket}', {_LINK_TS}), 'YYYY-MM-DD') AS week, count(*) AS done
            FROM backlink_records b
            WHERE b.workspace_id = :ws AND b.project_id = :pid
              AND {_LINK_TS} >= :t0 AND {_LINK_TS} < :t1{user_clause_b}{lt_clause}
            GROUP BY 1
        ),
        plan AS (
            SELECT to_char(date_trunc('{bucket}', a.day), 'YYYY-MM-DD') AS week,
                   coalesce(sum(a.expected_links), 0) AS target
            FROM task_assignments a
            WHERE a.workspace_id = :ws AND a.project_id = :pid
              AND a.day >= :pf AND a.day <= :t{user_clause_a}
            GROUP BY 1
        )
        SELECT coalesce(actuals.week, plan.week) AS week,
               coalesce(actuals.done, 0) AS done,
               coalesce(plan.target, 0) AS target
        FROM actuals FULL OUTER JOIN plan USING (week)
        ORDER BY 1
        """
    )
    weekly = [dict(r) for r in (await db.execute(trend_sql, p)).mappings().all()]

    return {
        "project_id": str(project_id),
        "from": t0.isoformat(),
        "to": t1.isoformat(),
        "totals": {**totals, "users": len([u for u in users_rows if u["user_label"] != "(unassigned)"])},
        "users": users_rows,
        "by_type": by_type,
        "weekly": weekly,
    }


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
    granularity: str = "week",
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
    bucket = granularity if granularity in ("day", "week", "month") else "week"
    where, wparams = _scope(ctx, project_id)
    wparams |= {"t0": t0, "t1": t1}
    weekly_sql = _bind(
        f"""
        SELECT to_char(date_trunc('{bucket}', {_LINK_TS}), 'YYYY-MM-DD') AS week,
               count(*) AS links,
               count(*) FILTER (WHERE b.index_status = 'indexed') AS indexed,
               count(*) FILTER (WHERE b.source_domain IS NOT NULL AND NOT EXISTS (
                   SELECT 1 FROM backlink_records e
                   WHERE e.project_id = b.project_id AND e.source_domain = b.source_domain
                     AND ({_LINK_TS_E}, e.id) < ({_LINK_TS}, b.id)
               )) AS new_domains
        FROM backlink_records b
        WHERE {where} AND {_LINK_TS} >= :t0 AND {_LINK_TS} < :t1
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
