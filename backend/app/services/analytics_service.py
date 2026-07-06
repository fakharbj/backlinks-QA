"""Dynamic analytics engine (Phase 5) — the ERP heart of the product.

One composable query layer over ``backlink_records``:
  • filters   — any combination of whitelisted dimensions (AND-combined),
  • summary   — headline counts/rates for the filtered set,
  • facets    — per-dimension value counts (each computed with the OTHER filters
                applied but not its own → "connected" filters the UI can show with
                live counts and disable when empty),
  • groups    — a group-by pivot (per user / project / link type / vendor / …) with
                per-group metrics (totals, score, pass/fail, indexed, nofollow, dups).

Everything is whitelisted (no user input is ever interpolated as a column/table)
and tenant + project scoped, so it stays safe and fast as dimensions grow.
"""

from __future__ import annotations

import uuid
from typing import Callable

from sqlalchemy import bindparam, text
from sqlalchemy.dialects.postgresql import ARRAY
from sqlalchemy.dialects.postgresql import UUID as PGUUID
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import settings
from app.core.deps import AuthContext

_EFF = "coalesce(b.override_status, b.status)"

# LEFT JOIN to the stored per-domain aggregates so KPI buckets (spam / orphaned /
# DA·PA·AS thresholds) resolve without a second scan. ``source_domains`` is unique
# per (workspace_id, domain_key) so this join never fans out the backlink rows.
# Injected ONCE into the summary/facets/groups FROM (there is no other ``sd`` alias
# in this module, so no alias collision). ``sd.id IS NULL`` ⇒ the link's source
# domain has no aggregate row (an "orphaned" link — see the ``orphaned`` metric).
_BASE_JOIN = (
    "LEFT JOIN source_domains sd "
    "ON sd.workspace_id = b.workspace_id AND sd.domain_key = b.source_domain"
)

# ── Whitelisted filters: key → (sql fragment, param-builder) ──────────────────────
# Each builder returns (clause, params) given the raw value; None → skip.


def _eq(col: str, key: str):
    return lambda v: (f"{col} = :{key}", {key: v})


def _eq_multi(col: str, key: str, *, lower: bool = False):
    """Single value OR comma-separated multi-select; ``(blanks)`` matches NULL/''.
    Emits ``col IN (...)`` with individually-bound params (never interpolated)."""

    def build(v):
        parts = [p.strip() for p in str(v).split(",") if p.strip()]
        want_blanks = any(p.lower() == "(blanks)" for p in parts)
        vals = [p.lower() if lower else p for p in parts if p.lower() != "(blanks)"]
        conds, params = [], {}
        if vals:
            names = []
            for i, val in enumerate(vals[:50]):
                pname = f"{key}_{i}"
                names.append(f":{pname}")
                params[pname] = val
            conds.append(f"{col} IN ({', '.join(names)})")
        if want_blanks:
            conds.append(f"({col} IS NULL OR {col} = '')")
        if not conds:
            return None
        clause = conds[0] if len(conds) == 1 else "(" + " OR ".join(conds) + ")"
        return (clause, params)

    return build


def _ilike_search(v):
    return (
        "(b.source_page_url ILIKE :q OR b.target_url ILIKE :q "
        "OR b.current_anchor_text ILIKE :q)",
        {"q": f"%{str(v).strip()}%"},
    )


def _http_class(v):
    ranges = {"2xx": (200, 300), "3xx": (300, 400), "4xx": (400, 500), "5xx": (500, 600)}
    if v not in ranges:
        return None
    lo, hi = ranges[v]
    return (f"b.http_status >= {lo} AND b.http_status < {hi}", {})


def _truthy(v) -> bool:
    """Interpret a query-string flag (true/1/yes) or a real bool as truthy."""
    return str(v).strip().lower() in ("1", "true", "yes", "on") if not isinstance(v, bool) else v


def _int_or_none(v):
    """Parse an int from a query value; return None for anything unparseable so a
    filter builder SKIPS instead of raising (mirrors the date builders)."""
    try:
        return int(str(v).strip())
    except (TypeError, ValueError):
        return None


# Score-band boundaries — MUST mirror qa/enums.py GradeBand.from_score:
#   perfect = 100 · good = 80–99 · warning = 60–79 · risky = 30–59 · failed = 0–29.
# Whitelisted CASE/range fragments (no user SQL); NULL score → matches nothing.
_SCORE_BAND_SQL = {
    "perfect": "b.score >= 100",
    "good": "b.score >= 80 AND b.score < 100",
    "warning": "b.score >= 60 AND b.score < 80",
    "risky": "b.score >= 30 AND b.score < 60",
    "failed": "b.score >= 0 AND b.score < 30",
}


def _score_band(v):
    """Single value or comma-list of grade bands → OR of the whitelisted ranges."""
    parts = [p.strip().lower() for p in str(v).split(",") if p.strip()]
    frags = [_SCORE_BAND_SQL[p] for p in parts if p in _SCORE_BAND_SQL]
    if not frags:
        return None
    clause = frags[0] if len(frags) == 1 else "(" + " OR ".join(f"({f})" for f in frags) + ")"
    return (clause, {})


def _index_status(v):
    conds, params = [], {}
    for i, part in enumerate([p.strip() for p in str(v).split(",") if p.strip()][:10]):
        if part == "unchecked":
            conds.append("b.index_status IS NULL")
        else:
            params[f"index_status_{i}"] = part
            conds.append(f"b.index_status = :index_status_{i}")
    if not conds:
        return None
    return ("(" + " OR ".join(conds) + ")", params)


def _duplicate_status(v):
    conds, params = [], {}
    for i, part in enumerate([p.strip() for p in str(v).split(",") if p.strip()][:10]):
        if part == "duplicate":
            conds.append("b.is_duplicate IS TRUE")
        elif part == "unique":
            conds.append("(b.is_duplicate IS NOT TRUE)")
        else:
            params[f"duplicate_status_{i}"] = part
            conds.append(f"b.duplicate_status = :duplicate_status_{i}")
    if not conds:
        return None
    return ("(" + " OR ".join(conds) + ")", params)


def _date_clause(lhs_op: str, key: str, v, *, next_day: bool = False):
    """Build a date comparison with a real ``date`` param (asyncpg rejects strings).
    ``next_day`` implements an inclusive end-of-day upper bound."""
    from datetime import date, timedelta

    try:
        d = date.fromisoformat(str(v)[:10])
    except ValueError:
        return None
    if next_day:
        d = d + timedelta(days=1)
    return (f"{lhs_op} :{key}", {key: d})


_FILTERS: dict[str, Callable] = {
    # Multi-select capable (comma lists + "(blanks)"), matching the Backlinks grid.
    "project_id": _eq_multi("b.project_id::text", "project_id"),
    "assigned_user_label": _eq_multi("b.assigned_user_label", "assigned_user_label"),
    "link_type": _eq_multi("b.link_type", "link_type"),
    "rel": _eq_multi("b.current_rel::text", "rel"),
    "indexability": _eq("b.indexability", "indexability"),
    "vendor_id": lambda v: ("b.vendor_id = :vendor_id", {"vendor_id": v}),
    "campaign_id": lambda v: ("b.campaign_id = :campaign_id", {"campaign_id": v}),
    "source_domain": _eq_multi("b.source_domain", "source_domain", lower=True),
    "target_domain": _eq("b.target_domain", "target_domain"),
    "status": _eq_multi(f"{_EFF}::text", "status"),
    "index_status": _index_status,
    "duplicate_status": _duplicate_status,
    "http_class": _http_class,
    # Exact HTTP status (single or comma-list, e.g. "200,301"). ``::text`` on the
    # column keeps it consistent with the multi-select IN-list builder.
    "http_status": _eq_multi("b.http_status::text", "http_status"),
    # Any 4xx/5xx = broken (only applies when truthy; falsy → filter skipped).
    "broken": lambda v: ("b.http_status >= 400", {}) if _truthy(v) else None,
    # Grade band mapped to score ranges (see GradeBand.from_score).
    "score_band": _score_band,
    # ── source_domains-backed filters (need _BASE_JOIN in the FROM) ────────────
    "spam": lambda v: (("sd.spam_score >= :spam_min", {"spam_min": _int_or_none(v)}) if _int_or_none(v) is not None else None),
    "da_min": lambda v: (("sd.da >= :da_min", {"da_min": _int_or_none(v)}) if _int_or_none(v) is not None else None),
    "pa_min": lambda v: (("sd.pa >= :pa_min", {"pa_min": _int_or_none(v)}) if _int_or_none(v) is not None else None),
    "as_min": lambda v: (("sd.semrush_as >= :as_min", {"as_min": _int_or_none(v)}) if _int_or_none(v) is not None else None),
    # Orphaned = the source domain has no source_domains aggregate row.
    "orphaned": lambda v: ("sd.id IS NULL", {}) if _truthy(v) else None,
    "link_missing": lambda v: ("b.link_found IS FALSE", {}) if _truthy(v) else None,
    "nofollow": lambda v: ("b.current_rel = 'nofollow'", {}) if _truthy(v) else None,
    "score_min": lambda v: ("b.score >= :score_min", {"score_min": int(v)}),
    "score_max": lambda v: ("b.score <= :score_max", {"score_max": int(v)}),
    "link_type_id": lambda v: ("b.link_type_id = :link_type_id", {"link_type_id": v}),
    "scoring_rule_version_id": lambda v: (
        "b.scoring_rule_version_id::text = :scoring_rule_version_id",
        {"scoring_rule_version_id": str(v)},
    ),
    "link_found": lambda v: ("b.link_found = :link_found", {"link_found": bool(v)}),
    "tag": lambda v: ("b.tags @> ARRAY[:tag]", {"tag": str(v)}),
    "search": _ilike_search,
    # NOTE: bare bind names + real ``date`` params — a `::` cast directly after a
    # bind name defeats SQLAlchemy text() parsing (`:p::t` binds nothing), and
    # asyncpg requires date/datetime objects, not strings. "to" bounds include
    # the whole end day. Invalid dates → builder returns None → filter skipped.
    "checked_from": lambda v: _date_clause("b.last_checked_at >=", "checked_from", v),
    "checked_to": lambda v: _date_clause("b.last_checked_at <", "checked_to", v, next_day=True),
    "created_from": lambda v: _date_clause("b.created_at >=", "created_from", v),
    "created_to": lambda v: _date_clause("b.created_at <", "created_to", v, next_day=True),
    "sheet_from": lambda v: _date_clause("b.sheet_created_date >=", "sheet_from", v),
    "sheet_to": lambda v: _date_clause("b.sheet_created_date <=", "sheet_to", v),
    # placement_date is a Date column → inclusive <= end (no next_day).
    "placement_from": lambda v: _date_clause("b.placement_date >=", "placement_from", v),
    "placement_to": lambda v: _date_clause("b.placement_date <=", "placement_to", v),
    # The rest are TIMESTAMPTZ → < to+1day so the end day is fully included.
    "discovered_from": lambda v: _date_clause("b.discovered_at >=", "discovered_from", v),
    "discovered_to": lambda v: _date_clause("b.discovered_at <", "discovered_to", v, next_day=True),
    "completed_from": lambda v: _date_clause("b.qa_completed_at >=", "completed_from", v),
    "completed_to": lambda v: _date_clause("b.qa_completed_at <", "completed_to", v, next_day=True),
    "assigned_from": lambda v: _date_clause("b.assigned_at >=", "assigned_from", v),
    "assigned_to": lambda v: _date_clause("b.assigned_at <", "assigned_to", v, next_day=True),
    "updated_from": lambda v: _date_clause("b.updated_at >=", "updated_from", v),
    "updated_to": lambda v: _date_clause("b.updated_at <", "updated_to", v, next_day=True),
    "index_from": lambda v: _date_clause("b.index_checked_at >=", "index_from", v),
    "index_to": lambda v: _date_clause("b.index_checked_at <", "index_to", v, next_day=True),
}

# ── Whitelisted group/facet dimensions: key → (key_expr, label_expr, extra_join) ──
_GROUPS: dict[str, tuple[str, str, str]] = {
    "project": ("b.project_id::text", "max(p.name)", "LEFT JOIN projects p ON p.id = b.project_id"),
    "user": ("coalesce(nullif(b.assigned_user_label, ''), '(unassigned)')", "''", ""),
    "employee_code": ("coalesce(nullif(b.employee_code, ''), '(none)')", "''", ""),
    "link_type": ("coalesce(nullif(b.link_type, ''), '(none)')", "''", ""),
    "rel": ("coalesce(b.current_rel::text, '(unknown)')", "''", ""),
    "status": (f"{_EFF}::text", "''", ""),
    "http_status": ("coalesce(b.http_status::text, '(none)')", "''", ""),
    # Grade band bucket — same boundaries as GradeBand.from_score / _score_band.
    "score_band": (
        "CASE "
        "WHEN b.score IS NULL THEN '(none)' "
        "WHEN b.score >= 100 THEN 'perfect' "
        "WHEN b.score >= 80 THEN 'good' "
        "WHEN b.score >= 60 THEN 'warning' "
        "WHEN b.score >= 30 THEN 'risky' "
        "ELSE 'failed' END",
        "''",
        "",
    ),
    "index_status": ("coalesce(b.index_status, 'unchecked')", "''", ""),
    "duplicate_status": ("coalesce(b.duplicate_status, 'unique')", "''", ""),
    "indexability": ("coalesce(b.indexability::text, 'unknown')", "''", ""),
    "vendor": ("coalesce(b.vendor_id::text, '(none)')", "max(ven.name)", "LEFT JOIN vendors ven ON ven.id = b.vendor_id"),
    "source_domain": ("b.source_domain", "''", ""),
    "scoring_version": (
        "coalesce(b.scoring_rule_version_id::text, '(none)')",
        "max(srv.scope || ' v' || srv.version)",
        "LEFT JOIN scoring_rule_versions srv ON srv.id = b.scoring_rule_version_id",
    ),
    # Month buckets (YYYY-MM) — whitelisted to_char expressions, no interpolation.
    "placement_month": ("to_char(b.placement_date, 'YYYY-MM')", "''", ""),
    "discovered_month": ("to_char(b.discovered_at, 'YYYY-MM')", "''", ""),
    "qa_month": ("to_char(b.last_checked_at, 'YYYY-MM')", "''", ""),
    "completed_month": ("to_char(b.qa_completed_at, 'YYYY-MM')", "''", ""),
    "imported_month": ("to_char(b.created_at, 'YYYY-MM')", "''", ""),
}

# Metric expressions reused by summary + groups.
_METRICS = f"""
    count(*)                                                  AS total,
    round(avg(b.score) FILTER (WHERE b.score IS NOT NULL), 1) AS avg_score,
    count(*) FILTER (WHERE {_EFF} = 'PASS')                   AS pass,
    count(*) FILTER (WHERE {_EFF} = 'WARNING')                AS warning,
    count(*) FILTER (WHERE {_EFF} = 'FAIL')                   AS fail,
    count(*) FILTER (WHERE {_EFF} = 'UNKNOWN')                AS unknown,
    count(*) FILTER (WHERE {_EFF} = 'NEEDS_MANUAL_REVIEW')    AS review,
    count(*) FILTER (WHERE {_EFF} = 'PENDING')                AS pending,
    count(*) FILTER (WHERE b.index_status = 'indexed')        AS indexed,
    count(*) FILTER (WHERE b.index_status = 'not_indexed')    AS not_indexed,
    count(*) FILTER (WHERE b.index_status IS NULL)            AS index_unchecked,
    count(*) FILTER (WHERE b.current_rel = 'nofollow')        AS nofollow,
    count(*) FILTER (WHERE b.current_rel = 'dofollow')        AS dofollow,
    count(*) FILTER (WHERE b.is_duplicate IS TRUE)            AS duplicates,
    count(*) FILTER (WHERE b.link_found IS FALSE)             AS link_missing,
    -- HTTP-status KPI buckets (single aggregate pass, no extra scan).
    count(*) FILTER (WHERE b.http_status = 200)               AS http_200,
    count(*) FILTER (WHERE b.http_status = 301)               AS http_301,
    count(*) FILTER (WHERE b.http_status = 302)               AS http_302,
    count(*) FILTER (WHERE b.http_status = 404)               AS http_404,
    count(*) FILTER (WHERE b.http_status >= 400)              AS broken,
    count(*) FILTER (WHERE b.http_status >= 300 AND b.http_status < 400) AS redirects,
    -- Source-domain-backed buckets (need _BASE_JOIN's ``sd`` alias in the FROM).
    count(*) FILTER (WHERE sd.spam_score >= :spam_threshold)  AS spam,
    -- orphaned = a link whose source domain has no source_domains aggregate row.
    count(*) FILTER (WHERE sd.id IS NULL)                     AS orphaned
"""


def _scope_clause(ctx: AuthContext) -> tuple[str, dict]:
    clause = "b.workspace_id = :ws"
    params: dict = {"ws": ctx.workspace_id}
    if ctx.allowed_project_ids is not None:
        clause += " AND b.project_id = ANY(:pids)"
        params["pids"] = list(ctx.allowed_project_ids) or [uuid.uuid4()]
    return clause, params


def _build_where(ctx: AuthContext, filters: dict, *, exclude: str | None = None) -> tuple[str, dict]:
    clauses, params = [], {}
    scope, sp = _scope_clause(ctx)
    clauses.append(scope)
    params |= sp
    for key, value in (filters or {}).items():
        if key == exclude or value in (None, "", []):
            continue
        builder = _FILTERS.get(key)
        if builder is None:
            continue
        built = builder(value)
        if built is None:
            continue
        clause, p = built
        clauses.append(clause)
        params |= p
    return " AND ".join(clauses), params


def _bind(sql: str, params: dict):
    t = text(sql)
    if "pids" in params:
        t = t.bindparams(bindparam("pids", type_=ARRAY(PGUUID(as_uuid=True))))
    return t


async def summary(db: AsyncSession, ctx: AuthContext, filters: dict) -> dict:
    where, params = _build_where(ctx, filters)
    params["spam_threshold"] = settings.ANALYTICS_SPAM_THRESHOLD
    sql = _bind(f"SELECT {_METRICS} FROM backlink_records b {_BASE_JOIN} WHERE {where}", params)
    row = (await db.execute(sql, params)).mappings().first() or {}
    out = {k: (float(v) if k == "avg_score" and v is not None else v) for k, v in row.items()}
    # Plain-English aliases the UI reads directly (PASS→qualified, FAIL→non_qualified).
    out["qualified"] = out.get("pass")
    out["non_qualified"] = out.get("fail")
    # Singular alias mirroring the dashboard KPI key (``duplicate``); the raw metric
    # column stays ``duplicates`` for backward-compat.
    out["duplicate"] = out.get("duplicates")
    return out


async def facets(
    db: AsyncSession, ctx: AuthContext, filters: dict, dimensions: list[str]
) -> dict:
    out: dict[str, list[dict]] = {}
    for dim in dimensions:
        spec = _GROUPS.get(dim)
        if spec is None:
            continue
        key_expr, label_expr, join = spec
        # Connected facet: apply all filters EXCEPT this dimension's own filter.
        own = _DIM_TO_FILTER.get(dim, dim)
        where, params = _build_where(ctx, filters, exclude=own)
        # _BASE_JOIN first so ``sd.*`` filters (spam/da_min/orphaned…) resolve; the
        # per-dimension ``join`` uses distinct aliases (p/ven/srv) → no sd collision.
        sql = _bind(
            f"SELECT {key_expr} AS value, {label_expr} AS label, count(*) AS n "
            f"FROM backlink_records b {_BASE_JOIN} {join} WHERE {where} "
            f"GROUP BY {key_expr} ORDER BY n DESC LIMIT 50",
            params,
        )
        rows = (await db.execute(sql, params)).mappings().all()
        out[dim] = [
            {"value": r["value"], "label": r["label"] or r["value"], "count": r["n"]}
            for r in rows
        ]
    return out


async def groups(
    db: AsyncSession, ctx: AuthContext, filters: dict, group_by: str, *, limit: int = 100
) -> list[dict]:
    spec = _GROUPS.get(group_by)
    if spec is None:
        return []
    key_expr, label_expr, join = spec
    where, params = _build_where(ctx, filters)
    params["lim"] = limit
    params["spam_threshold"] = settings.ANALYTICS_SPAM_THRESHOLD
    # _BASE_JOIN first (sd alias for the KPI buckets + sd.* filters); per-dim join
    # uses distinct aliases → no sd collision.
    sql = _bind(
        f"""
        SELECT {key_expr} AS key, {label_expr} AS label, {_METRICS}
        FROM backlink_records b {_BASE_JOIN} {join}
        WHERE {where}
        GROUP BY {key_expr}
        ORDER BY total DESC
        LIMIT :lim
        """,
        params,
    )
    rows = (await db.execute(sql, params)).mappings().all()
    return [dict(r) for r in rows]


# Map a group/facet dimension to the filter key it corresponds to (for connected facets).
_DIM_TO_FILTER = {
    "project": "project_id", "user": "assigned_user_label", "employee_code": "employee_code",
    "link_type": "link_type", "rel": "rel", "status": "status", "index_status": "index_status",
    "duplicate_status": "duplicate_status", "indexability": "indexability", "vendor": "vendor_id",
    "source_domain": "source_domain", "scoring_version": "scoring_rule_version_id",
    "http_status": "http_status", "score_band": "score_band",
}


async def records(
    db: AsyncSession,
    ctx: AuthContext,
    filters: dict,
    group_by: str,
    group_key: str,
    *,
    limit: int = 50,
) -> list[dict]:
    """Drill-down: the backlinks behind one analytics group cell. Reuses the group's
    own key expression (``key_expr = :gkey``) so coalesced buckets like '(none)'
    match exactly the rows that were counted."""
    spec = _GROUPS.get(group_by)
    if spec is None:
        return []
    key_expr = spec[0]
    where, params = _build_where(ctx, filters)
    params["gkey"] = group_key
    params["lim"] = max(1, min(int(limit), 500))
    sql = _bind(
        f"""
        SELECT b.id::text AS id, b.source_page_url, b.target_url,
               {_EFF}::text AS status, b.score, b.link_found,
               b.current_rel::text AS current_rel, b.link_type, b.source_domain
        FROM backlink_records b {_BASE_JOIN}
        WHERE {where} AND {key_expr} = :gkey
        ORDER BY b.score ASC NULLS LAST
        LIMIT :lim
        """,
        params,
    )
    rows = (await db.execute(sql, params)).mappings().all()
    return [dict(r) for r in rows]


def allowed_dimensions() -> list[str]:
    return list(_GROUPS.keys())
