"""Dashboard aggregation — reads materialized views for sub-2s loads (Arch §10).

Matviews are not ORM-mapped, so they're queried via parameterised ``text()``. Tenant
+ project scoping is always applied. Time-window "lost" counts come from the
(indexed, partitioned) ``backlink_history`` table.
"""

from __future__ import annotations

import uuid
from datetime import datetime, timedelta, timezone

from sqlalchemy import bindparam, text
from sqlalchemy.dialects.postgresql import ARRAY
from sqlalchemy.dialects.postgresql import UUID as PGUUID
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.deps import AuthContext
from app.schemas.dashboard import (
    DashboardResponse,
    DomainFailure,
    IssueTotals,
    LostWindow,
    RecentChange,
    StatusTotals,
    VendorFailure,
)


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

    totals_sql, _ = _bind(
        f"""
        SELECT
            coalesce(sum(total),0)                                    AS total,
            coalesce(sum(pass_count),0)                               AS pass_count,
            coalesce(sum(warning_count),0)                            AS warning_count,
            coalesce(sum(fail_count),0)                               AS fail_count,
            coalesce(sum(unknown_count),0)                            AS unknown_count,
            coalesce(sum(review_count),0)                             AS review_count,
            coalesce(sum(pending_count),0)                            AS pending_count,
            CASE WHEN sum(total) > 0
                 THEN round(sum(avg_score*total)/nullif(sum(total),0),1) END AS avg_score,
            coalesce(sum(nofollow_count),0)                           AS nofollow_count,
            coalesce(sum(noindex_count),0)                            AS noindex_count,
            coalesce(sum(robots_blocked_count),0)                     AS robots_blocked_count,
            coalesce(sum(canonical_issue_count),0)                    AS canonical_issue_count,
            coalesce(sum(broken_count),0)                             AS broken_count,
            coalesce(sum(link_missing_count),0)                       AS link_missing_count
        FROM mv_project_dashboard WHERE {where}
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
    domains = await _top_domains(db, where, params)
    vendors = await _top_vendors(db, where, params)
    recent = await _recent_changes(db, ctx, project_id)

    return DashboardResponse(
        totals=totals, issues=issues, lost=lost,
        top_failing_domains=domains, top_vendors_by_failure=vendors, recent_changes=recent,
    )


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


async def _top_domains(db: AsyncSession, where: str, params: dict) -> list[DomainFailure]:
    sql, _ = _bind(
        f"""
        SELECT source_domain, total, fail_count, failure_rate
        FROM mv_domain_failures
        WHERE {where} AND fail_count > 0
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


async def _top_vendors(db: AsyncSession, where: str, params: dict) -> list[VendorFailure]:
    sql, _ = _bind(
        f"""
        SELECT v.id AS vendor_id, ven.name AS vendor_name, v.total, v.fail_count,
               v.failure_rate, v.avg_score
        FROM mv_vendor_failure_rates v
        LEFT JOIN vendors ven ON ven.id = v.vendor_id
        WHERE {where} AND v.fail_count > 0
        ORDER BY v.failure_rate DESC NULLS LAST, v.fail_count DESC
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
