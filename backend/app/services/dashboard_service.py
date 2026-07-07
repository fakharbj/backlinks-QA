"""Dashboard aggregation — live queries over the backlink table (always fresh).

Status totals and the issue-mix come straight from ``backlink_records`` so the
dashboard never lags a crawl (no materialized-view refresh in the hot path — that
indirection caused stale zeros). Time-window "lost" counts and the recent-changes
feed come from the partitioned ``backlink_history`` table. Tenant + project
scoping is always applied.

At very large scale the per-domain / per-vendor rollups can be moved back onto the
``mv_*`` materialized views (kept in ``db/ddl.py``); for typical workspaces the
live queries are instantaneous and correct by construction.
"""

from __future__ import annotations

import uuid
from datetime import datetime, timedelta, timezone

from sqlalchemy import bindparam, text
from sqlalchemy.dialects.postgresql import ARRAY
from sqlalchemy.dialects.postgresql import UUID as PGUUID
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import settings
from app.core.deps import AuthContext
from app.schemas.dashboard import (
    AssignedUserStat,
    DashboardResponse,
    DomainFailure,
    IssueTotals,
    LinkTypeBreakdown,
    LostWindow,
    RecentChange,
    RecentRegression,
    StatusTotals,
    TopSourceDomain,
    TrendPoint,
    VendorFailure,
)


def _effective(prefix: str = "") -> str:
    """Effective status = manual override when present, else computed verdict."""
    p = f"{prefix}." if prefix else ""
    return f"coalesce({p}override_status, {p}status)"


def _scope_clause(
    ctx: AuthContext, project_id: uuid.UUID | None, *, prefix: str = ""
) -> tuple[str, dict]:
    p = f"{prefix}." if prefix else ""
    clause = f"{p}workspace_id = :ws"
    params: dict = {"ws": ctx.workspace_id}
    if project_id is not None:
        ctx.assert_project(project_id)
        clause += f" AND {p}project_id = :pid"
        params["pid"] = project_id
    elif ctx.allowed_project_ids is not None:
        clause += f" AND {p}project_id = ANY(:pids)"
        params["pids"] = list(ctx.allowed_project_ids) or [uuid.uuid4()]
    return clause, params


def _bind(stmt: str, params: dict):
    t = text(stmt)
    if "pids" in params:
        t = t.bindparams(bindparam("pids", type_=ARRAY(PGUUID(as_uuid=True))))
    return t, params


async def build_dashboard(
    db: AsyncSession, ctx: AuthContext, project_id: uuid.UUID | None = None
) -> DashboardResponse:
    where, params = _scope_clause(ctx, project_id)
    eff = _effective()

    totals_sql, _ = _bind(
        f"""
        SELECT
            count(*)                                                  AS total,
            count(*) FILTER (WHERE {eff} = 'PASS')                    AS pass_count,
            count(*) FILTER (WHERE {eff} = 'WARNING')                 AS warning_count,
            count(*) FILTER (WHERE {eff} = 'FAIL')                    AS fail_count,
            count(*) FILTER (WHERE {eff} = 'UNKNOWN')                 AS unknown_count,
            count(*) FILTER (WHERE {eff} = 'NEEDS_MANUAL_REVIEW')     AS review_count,
            count(*) FILTER (WHERE {eff} = 'PENDING')                 AS pending_count,
            round(avg(score) FILTER (WHERE score IS NOT NULL), 1)     AS avg_score,
            count(*) FILTER (WHERE current_rel = 'nofollow')          AS nofollow_count,
            count(*) FILTER (WHERE indexability = 'not_indexable')    AS noindex_count,
            count(*) FILTER (WHERE robots_status = 'blocked')         AS robots_blocked_count,
            count(*) FILTER (WHERE canonical_status IN ('mismatch','cross_domain'))
                                                                      AS canonical_issue_count,
            count(*) FILTER (WHERE http_status >= 400)                AS broken_count,
            count(*) FILTER (WHERE link_found = false)                AS link_missing_count
        FROM backlink_records
        WHERE {where}
        """,
        params,
    )
    row = (await db.execute(totals_sql, params)).mappings().first() or {}

    totals = StatusTotals(
        total=row.get("total", 0), pass_count=row.get("pass_count", 0),
        warning_count=row.get("warning_count", 0), fail_count=row.get("fail_count", 0),
        unknown_count=row.get("unknown_count", 0), review_count=row.get("review_count", 0),
        pending_count=row.get("pending_count", 0), avg_score=row.get("avg_score"),
    )
    issues = IssueTotals(
        nofollow_count=row.get("nofollow_count", 0), noindex_count=row.get("noindex_count", 0),
        robots_blocked_count=row.get("robots_blocked_count", 0),
        canonical_issue_count=row.get("canonical_issue_count", 0),
        broken_count=row.get("broken_count", 0), link_missing_count=row.get("link_missing_count", 0),
    )

    lost = await _lost_window(db, ctx, project_id)
    domains = await _top_domains(db, ctx, project_id)
    vendors = await _top_vendors(db, ctx, project_id)
    recent = await _recent_changes(db, ctx, project_id)
    kpi = await _kpi_counts(db, ctx, project_id)

    # Company view: entity totals strip (owners: "no of projects, competitors…").
    extra: dict = {}
    if project_id is None:
        counts_row = (
            await db.execute(
                text(
                    """
                    SELECT
                      (SELECT count(*) FROM projects WHERE workspace_id = :ws)              AS projects,
                      (SELECT count(*) FROM source_domains WHERE workspace_id = :ws)        AS source_domains,
                      (SELECT count(*) FROM competitor_source_domains WHERE workspace_id = :ws) AS competitor_domains,
                      (SELECT count(*) FROM workspace_members WHERE workspace_id = :ws)     AS users,
                      (SELECT count(*) FROM batches WHERE workspace_id = :ws)               AS batches,
                      (SELECT count(*) FROM backlink_conflicts
                        WHERE workspace_id = :ws AND resolution_status = 'open')            AS open_duplicates,
                      (SELECT count(*) FROM backlink_records
                        WHERE workspace_id = :ws AND index_status = 'indexed')              AS indexed_links
                    """
                ),
                {"ws": ctx.workspace_id},
            )
        ).mappings().first() or {}
        extra = {"counts": dict(counts_row)}

    # Deeper, project-specific sections (only for a single-project dashboard).
    if project_id is not None:
        extra = dict(
            is_project=True,
            link_type_breakdown=await _link_type_breakdown(db, ctx, project_id),
            trends=await _trends(db, ctx, project_id),
            top_source_domains=await _top_source_domains(db, ctx, project_id),
            recent_regressions=await _recent_regressions(db, ctx, project_id),
            assigned_user_stats=await _assigned_user_stats(db, ctx, project_id),
        )

    return DashboardResponse(
        totals=totals, issues=issues, lost=lost, kpi=kpi,
        top_failing_domains=domains, top_vendors_by_failure=vendors, recent_changes=recent,
        **extra,
    )


async def _kpi_counts(
    db: AsyncSession, ctx: AuthContext, project_id: uuid.UUID | None
) -> dict:
    """Headline KPI boxes for the Overview — one aggregate pass, project-scoped +
    RBAC-scoped (``allowed_project_ids``) exactly like the status totals.

    HTTP buckets + qualified/non-qualified (effective status) come from the
    backlink table; ``spam`` and ``orphaned`` need the per-domain aggregate, so we
    LEFT JOIN ``source_domains sd`` (unique per workspace+domain_key → no fan-out).
    ``orphaned`` = a link whose source domain has no source_domains aggregate row.
    """
    where, params = _scope_clause(ctx, project_id, prefix="b")
    eff = _effective("b")
    params["spam_threshold"] = settings.ANALYTICS_SPAM_THRESHOLD
    sql, _ = _bind(
        f"""
        SELECT
            count(*) FILTER (WHERE b.http_status = 200)  AS http_200,
            count(*) FILTER (WHERE b.http_status = 301)  AS http_301,
            count(*) FILTER (WHERE b.http_status = 302)  AS http_302,
            count(*) FILTER (WHERE b.http_status = 404)  AS http_404,
            count(*) FILTER (WHERE b.http_status >= 400) AS broken,
            count(*) FILTER (WHERE b.index_status = 'indexed')     AS indexed,
            count(*) FILTER (WHERE b.index_status = 'not_indexed') AS not_indexed,
            count(*) FILTER (WHERE {eff} = 'PASS')       AS qualified,
            count(*) FILTER (WHERE {eff} = 'FAIL')       AS non_qualified,
            count(*) FILTER (WHERE b.is_duplicate IS TRUE)          AS duplicate,
            count(*) FILTER (WHERE sd.spam_score >= :spam_threshold) AS spam,
            count(*) FILTER (WHERE sd.id IS NULL)        AS orphaned
        FROM backlink_records b
        LEFT JOIN source_domains sd
          ON sd.workspace_id = b.workspace_id AND sd.domain_key = b.source_domain
        WHERE {where}
        """,
        params,
    )
    row = (await db.execute(sql, params)).mappings().first() or {}
    return {k: int(v or 0) for k, v in row.items()}


async def _link_type_breakdown(db, ctx, project_id) -> list[LinkTypeBreakdown]:
    where, params = _scope_clause(ctx, project_id)
    eff = _effective()
    sql, _ = _bind(
        f"""
        SELECT coalesce(nullif(link_type, ''), '(none)') AS link_type,
               count(*)                                  AS total,
               count(*) FILTER (WHERE {eff} = 'PASS')    AS pass_count,
               count(*) FILTER (WHERE {eff} = 'FAIL')    AS fail_count,
               round(avg(score) FILTER (WHERE score IS NOT NULL), 1) AS avg_score
        FROM backlink_records WHERE {where}
        GROUP BY 1 ORDER BY total DESC LIMIT 30
        """,
        params,
    )
    return [LinkTypeBreakdown(**m) for m in (await db.execute(sql, params)).mappings().all()]


async def _trends(db, ctx, project_id, days: int = 14) -> list[TrendPoint]:
    where, params = _scope_clause(ctx, project_id)
    params["since"] = datetime.now(timezone.utc) - timedelta(days=days)
    sql, _ = _bind(
        f"""
        SELECT to_char(date_trunc('day', created_at), 'YYYY-MM-DD')       AS date,
               count(*) FILTER (WHERE event_type = 'link_added')          AS added,
               count(*) FILTER (WHERE event_type = 'link_removed')        AS removed,
               count(*) FILTER (WHERE event_type = 'score_changed')       AS score_changed
        FROM backlink_history WHERE {where} AND created_at >= :since
        GROUP BY 1 ORDER BY 1 ASC
        """,
        params,
    )
    return [TrendPoint(**m) for m in (await db.execute(sql, params)).mappings().all()]


async def _top_source_domains(db, ctx, project_id) -> list[TopSourceDomain]:
    where, params = _scope_clause(ctx, project_id)
    eff = _effective()
    sql, _ = _bind(
        f"""
        SELECT source_domain,
               count(*)                                AS total,
               count(*) FILTER (WHERE {eff} = 'PASS')  AS pass_count,
               count(*) FILTER (WHERE {eff} = 'FAIL')  AS fail_count,
               round(100.0 * count(*) FILTER (WHERE index_status = 'indexed')
                     / nullif(count(*), 0), 1)         AS indexed_pct
        FROM backlink_records WHERE {where} AND source_domain IS NOT NULL
        GROUP BY source_domain ORDER BY total DESC LIMIT 10
        """,
        params,
    )
    return [TopSourceDomain(**m) for m in (await db.execute(sql, params)).mappings().all()]


async def _recent_regressions(db, ctx, project_id) -> list[RecentRegression]:
    where, params = _scope_clause(ctx, project_id, prefix="h")
    sql, _ = _bind(
        f"""
        SELECT h.backlink_id, b.source_page_url, h.event_type, h.severity,
               h.field, h.old_value, h.new_value, h.created_at
        FROM backlink_history h JOIN backlink_records b ON b.id = h.backlink_id
        WHERE {where} AND h.severity IN ('CRITICAL', 'HIGH')
        ORDER BY h.created_at DESC LIMIT 15
        """,
        params,
    )
    return [RecentRegression(**m) for m in (await db.execute(sql, params)).mappings().all()]


async def trends(
    db: AsyncSession,
    ctx: AuthContext,
    *,
    days: int = 30,
    project_id: uuid.UUID | None = None,
) -> dict:
    """Timeframe stats + equal-length previous-period comparison + weekly series.
    'New domains' uses the owner rule: first-ever appearance of the domain in the
    scope (project when selected, else workspace).

    Micro-cached in Redis for 30s: dashboards are read far more often than data
    changes, so repeat loads answer in a few ms without touching Postgres."""
    import json as _json

    cache_key = f"ls:dash:trends:{ctx.workspace_id}:{project_id}:{days}"
    try:
        from app.core.redis import get_redis

        cached = await get_redis().get(cache_key)
        if cached:
            return _json.loads(cached)
    except Exception:  # noqa: BLE001 — cache is best-effort
        pass
    result = await _trends_uncached(db, ctx, days=days, project_id=project_id)
    try:
        from app.core.redis import get_redis

        await get_redis().set(cache_key, _json.dumps(result), ex=30)
    except Exception:  # noqa: BLE001
        pass
    return result


async def _trends_uncached(
    db: AsyncSession,
    ctx: AuthContext,
    *,
    days: int = 30,
    project_id: uuid.UUID | None = None,
) -> dict:
    where, params = _scope_clause(ctx, project_id, prefix="b")
    days = max(1, min(days, 3660))
    now = datetime.now(timezone.utc)
    t0 = now - timedelta(days=days)
    prev0 = t0 - timedelta(days=days)
    params |= {"t0": t0, "t1": now, "p0": prev0}
    first_scope = (
        "e.project_id = b.project_id" if project_id is not None else "e.workspace_id = b.workspace_id"
    )
    # A link is "the first ever from its domain" when no OTHER link from that domain
    # is earlier. Ties matter: a bulk import gives every row the SAME created_at
    # (Postgres now() is constant within a transaction), so a bare `<` on created_at
    # would count EVERY link of a same-day domain as new — inflating the count above
    # the distinct-domain total. Order by the real creation (placement) date, then a
    # unique id tiebreaker, so exactly ONE link per domain qualifies.
    new_domain = (
        "b.source_domain IS NOT NULL AND NOT EXISTS ("
        "SELECT 1 FROM backlink_records e "
        f"WHERE {first_scope} AND e.source_domain = b.source_domain "
        "AND (coalesce(e.placement_date, e.created_at), e.id) "
        "  < (coalesce(b.placement_date, b.created_at), b.id))"
    )

    # Bucket the Activity trend by the link's REAL creation/placement day (from the
    # sheet), not by when the row was imported — so the chart reflects when work
    # actually happened. Falls back to import time only when no sheet date exists.
    eff = "coalesce(b.placement_date, b.created_at)"
    sql, _ = _bind(
        f"""
        SELECT
            count(*) FILTER (WHERE {eff} >= :t0)                       AS new_links,
            count(*) FILTER (WHERE {eff} >= :t0 AND {new_domain})      AS new_domains,
            count(*) FILTER (WHERE {eff} >= :p0 AND {eff} < :t0)       AS prev_links,
            count(*) FILTER (
                WHERE {eff} >= :p0 AND {eff} < :t0 AND {new_domain}
            )                                                          AS prev_domains,
            count(*) FILTER (WHERE {eff} >= :t0 AND b.index_status = 'indexed') AS new_indexed
        FROM backlink_records b
        WHERE {where} AND {eff} >= :p0
        """,
        params,
    )
    head = (await db.execute(sql, params)).mappings().first() or {}

    weekly_sql, _ = _bind(
        f"""
        SELECT to_char(date_trunc('week', {eff}), 'YYYY-MM-DD') AS week,
               count(*) AS links,
               count(*) FILTER (WHERE {new_domain}) AS new_domains
        FROM backlink_records b
        WHERE {where} AND {eff} >= :t0
        GROUP BY 1 ORDER BY 1 ASC
        """,
        params,
    )
    weekly = [dict(r) for r in (await db.execute(weekly_sql, params)).mappings().all()]

    new_domains = head.get("new_domains", 0)
    prev_domains = head.get("prev_domains", 0)
    # GLOBAL (company) scope: "new source domains" = catalog additions by discovery
    # date (earliest of first-backlink placement or import/competitor-promotion),
    # so imported/promoted domains count too — not just backlink first-appearances.
    # Project scope stays on "first backlink for this project" above (source_domains
    # is workspace-scoped, and that already matches the project rule).
    if project_id is None:
        dsql, _ = _bind(
            """
            SELECT count(*) FILTER (WHERE discovery_date >= :t0)                     AS nd,
                   count(*) FILTER (WHERE discovery_date >= :p0 AND discovery_date < :t0) AS pd
            FROM source_domains WHERE workspace_id = :ws
            """,
            {"ws": ctx.workspace_id, "t0": t0, "p0": prev0},
        )
        drow = (await db.execute(dsql, {"ws": ctx.workspace_id, "t0": t0, "p0": prev0})).mappings().first() or {}
        new_domains = int(drow.get("nd") or 0)
        prev_domains = int(drow.get("pd") or 0)
        wsql, _ = _bind(
            """
            SELECT to_char(date_trunc('week', discovery_date), 'YYYY-MM-DD') AS week, count(*) AS n
            FROM source_domains WHERE workspace_id = :ws AND discovery_date >= :t0
            GROUP BY 1
            """,
            {"ws": ctx.workspace_id, "t0": t0},
        )
        wkmap = {r["week"]: int(r["n"]) for r in (await db.execute(wsql, {"ws": ctx.workspace_id, "t0": t0})).mappings().all()}
        seen = set()
        for w in weekly:
            w["new_domains"] = wkmap.get(w["week"], 0)
            seen.add(w["week"])
        for week, n in wkmap.items():
            if week not in seen:
                weekly.append({"week": week, "links": 0, "new_domains": n})
        weekly.sort(key=lambda w: w["week"])

    return {
        "days": days,
        "new_links": head.get("new_links", 0),
        "new_domains": new_domains,
        "new_indexed": head.get("new_indexed", 0),
        "prev_links": head.get("prev_links", 0),
        "prev_domains": prev_domains,
        "weekly": weekly,
    }


async def _assigned_user_stats(db, ctx, project_id) -> list[AssignedUserStat]:
    where, params = _scope_clause(ctx, project_id)
    eff = _effective()
    sql, _ = _bind(
        f"""
        SELECT coalesce(nullif(assigned_user_label, ''), '(unassigned)') AS assigned_user_label,
               count(*)                                  AS total,
               count(*) FILTER (WHERE {eff} = 'PASS')    AS pass_count,
               count(*) FILTER (WHERE {eff} = 'FAIL')    AS fail_count,
               round(avg(score) FILTER (WHERE score IS NOT NULL), 1) AS avg_score
        FROM backlink_records WHERE {where}
        GROUP BY 1 ORDER BY total DESC LIMIT 30
        """,
        params,
    )
    return [AssignedUserStat(**m) for m in (await db.execute(sql, params)).mappings().all()]


async def _lost_window(
    db: AsyncSession, ctx: AuthContext, project_id: uuid.UUID | None
) -> LostWindow:
    where, params = _scope_clause(ctx, project_id)
    now = datetime.now(timezone.utc)
    params |= {
        "day": now - timedelta(days=1),
        "week": now - timedelta(days=7),
        "month": now - timedelta(days=30),
    }
    sql, _ = _bind(
        f"""
        SELECT
            count(*) FILTER (WHERE created_at >= :day)   AS today,
            count(*) FILTER (WHERE created_at >= :week)  AS week,
            count(*) FILTER (WHERE created_at >= :month) AS month
        FROM backlink_history
        WHERE {where} AND event_type = 'link_removed' AND created_at >= :month
        """,
        params,
    )
    r = (await db.execute(sql, params)).mappings().first() or {}
    return LostWindow(today=r.get("today", 0), week=r.get("week", 0), month=r.get("month", 0))


async def _top_domains(
    db: AsyncSession, ctx: AuthContext, project_id: uuid.UUID | None
) -> list[DomainFailure]:
    where, params = _scope_clause(ctx, project_id)
    eff = _effective()
    sql, _ = _bind(
        f"""
        SELECT source_domain,
               count(*)                                AS total,
               count(*) FILTER (WHERE {eff} = 'FAIL')  AS fail_count,
               round(100.0 * count(*) FILTER (WHERE {eff} = 'FAIL')
                     / nullif(count(*), 0), 1)         AS failure_rate
        FROM backlink_records
        WHERE {where} AND source_domain IS NOT NULL
        GROUP BY source_domain
        HAVING count(*) FILTER (WHERE {eff} = 'FAIL') > 0
        ORDER BY fail_count DESC, failure_rate DESC NULLS LAST
        LIMIT 10
        """,
        params,
    )
    return [
        DomainFailure(source_domain=m["source_domain"], total=m["total"],
                      fail_count=m["fail_count"], failure_rate=m["failure_rate"])
        for m in (await db.execute(sql, params)).mappings().all()
    ]


async def _top_vendors(
    db: AsyncSession, ctx: AuthContext, project_id: uuid.UUID | None
) -> list[VendorFailure]:
    # Prefix with ``b`` so ``workspace_id`` is unambiguous across the vendors join.
    where, params = _scope_clause(ctx, project_id, prefix="b")
    eff = _effective("b")
    sql, _ = _bind(
        f"""
        SELECT b.vendor_id, ven.name AS vendor_name,
               count(*)                                  AS total,
               count(*) FILTER (WHERE {eff} = 'FAIL')    AS fail_count,
               round(100.0 * count(*) FILTER (WHERE {eff} = 'FAIL')
                     / nullif(count(*), 0), 1)           AS failure_rate,
               round(avg(b.score) FILTER (WHERE b.score IS NOT NULL), 1) AS avg_score
        FROM backlink_records b
        LEFT JOIN vendors ven ON ven.id = b.vendor_id
        WHERE {where} AND b.vendor_id IS NOT NULL
        GROUP BY b.vendor_id, ven.name
        HAVING count(*) FILTER (WHERE {eff} = 'FAIL') > 0
        ORDER BY failure_rate DESC NULLS LAST, fail_count DESC
        LIMIT 10
        """,
        params,
    )
    return [
        VendorFailure(vendor_id=m["vendor_id"], vendor_name=m["vendor_name"], total=m["total"],
                      fail_count=m["fail_count"], failure_rate=m["failure_rate"],
                      avg_score=m["avg_score"])
        for m in (await db.execute(sql, params)).mappings().all()
    ]


async def _recent_changes(
    db: AsyncSession, ctx: AuthContext, project_id: uuid.UUID | None
) -> list[RecentChange]:
    where, params = _scope_clause(ctx, project_id, prefix="h")
    sql, _ = _bind(
        f"""
        SELECT h.backlink_id, b.source_page_url, h.event_type, h.severity, h.created_at
        FROM backlink_history h
        JOIN backlink_records b ON b.id = h.backlink_id
        WHERE {where}
          AND h.event_type <> 'first_crawl'
        ORDER BY h.created_at DESC
        LIMIT 15
        """,
        params,
    )
    return [
        RecentChange(backlink_id=m["backlink_id"], source_page_url=m["source_page_url"],
                     event_type=m["event_type"], severity=m["severity"], created_at=m["created_at"])
        for m in (await db.execute(sql, params)).mappings().all()
    ]
