"""Source main-domain aggregation + analytics (Phase 8, features 11/12/14).

``recompute`` refreshes the stored per-domain counters with a few set-based SQL
statements (scales to millions of rows in one pass), links each backlink to its
``source_domain``, and drops orphans. ``list_domains`` / ``detail`` serve the
dashboard from the stored aggregates so ratios never scan the backlink table.
"""

from __future__ import annotations

import uuid

from sqlalchemy import func, or_, select, text
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import settings
from app.core.deps import AuthContext
from app.core.errors import NotFoundError
from app.models.backlink import BacklinkRecord
from app.models.project import Project
from app.models.source_domain import SourceDomain

# ── Set-based refresh SQL (:ws is a uuid bind param) ──────────────────────────
_UPSERT = text(
    """
    INSERT INTO source_domains (
        id, workspace_id, domain_key, grouping, backlink_count, indexed_count,
        not_indexed_count, uncertain_count, unchecked_count, dofollow_count,
        nofollow_count, duplicate_count, link_type_distribution, avg_score,
        project_count, user_count, last_recomputed_at, created_at, updated_at)
    SELECT gen_random_uuid(), workspace_id, source_domain, 'registrable',
        count(*),
        count(*) FILTER (WHERE index_status = 'indexed'),
        count(*) FILTER (WHERE index_status = 'not_indexed'),
        count(*) FILTER (WHERE index_status = 'uncertain'),
        count(*) FILTER (WHERE index_status IS NULL),
        count(*) FILTER (WHERE current_rel::text = 'dofollow'),
        count(*) FILTER (WHERE current_rel::text = 'nofollow'),
        count(*) FILTER (WHERE is_duplicate),
        '{}'::jsonb,
        round(avg(score)::numeric, 1),
        count(DISTINCT project_id),
        count(DISTINCT nullif(btrim(assigned_user_label), '')),
        now(), now(), now()
    FROM backlink_records
    WHERE workspace_id = :ws AND source_domain IS NOT NULL AND source_domain <> ''
    GROUP BY workspace_id, source_domain
    ON CONFLICT (workspace_id, domain_key) DO UPDATE SET
        backlink_count = EXCLUDED.backlink_count,
        indexed_count = EXCLUDED.indexed_count,
        not_indexed_count = EXCLUDED.not_indexed_count,
        uncertain_count = EXCLUDED.uncertain_count,
        unchecked_count = EXCLUDED.unchecked_count,
        dofollow_count = EXCLUDED.dofollow_count,
        nofollow_count = EXCLUDED.nofollow_count,
        duplicate_count = EXCLUDED.duplicate_count,
        avg_score = EXCLUDED.avg_score,
        project_count = EXCLUDED.project_count,
        user_count = EXCLUDED.user_count,
        last_recomputed_at = now(),
        updated_at = now();
    """
)

_DIST = text(
    """
    UPDATE source_domains sd
    SET link_type_distribution = COALESCE(d.dist, '{}'::jsonb), updated_at = now()
    FROM (
        SELECT source_domain, jsonb_object_agg(lt, cnt) AS dist FROM (
            SELECT source_domain, COALESCE(NULLIF(btrim(link_type), ''), '(unset)') AS lt,
                   count(*) AS cnt
            FROM backlink_records
            WHERE workspace_id = :ws AND source_domain IS NOT NULL AND source_domain <> ''
            GROUP BY source_domain, lt
        ) x GROUP BY source_domain
    ) d
    WHERE sd.workspace_id = :ws AND sd.domain_key = d.source_domain;
    """
)

_LINK = text(
    """
    UPDATE backlink_records b SET source_domain_id = sd.id
    FROM source_domains sd
    WHERE sd.workspace_id = b.workspace_id AND sd.domain_key = b.source_domain
      AND b.workspace_id = :ws AND b.source_domain_id IS DISTINCT FROM sd.id;
    """
)

_ORPHAN = text(
    """
    DELETE FROM source_domains sd
    WHERE sd.workspace_id = :ws AND NOT EXISTS (
        SELECT 1 FROM backlink_records b
        WHERE b.workspace_id = sd.workspace_id AND b.source_domain = sd.domain_key);
    """
)

_SORT_COLUMNS = {
    "domain": SourceDomain.domain_key,
    "backlinks": SourceDomain.backlink_count,
    "avg_score": SourceDomain.avg_score,
    "duplicates": SourceDomain.duplicate_count,
    "indexed": SourceDomain.indexed_count,
}


async def recompute(db: AsyncSession, workspace_id: uuid.UUID) -> int:
    """Refresh stored source-domain aggregates for a workspace. Idempotent."""
    params = {"ws": workspace_id}
    await db.execute(_UPSERT, params)
    await db.execute(_DIST, params)
    await db.execute(_LINK, params)
    await db.execute(_ORPHAN, params)
    await db.flush()
    return int(
        (
            await db.execute(
                select(func.count())
                .select_from(SourceDomain)
                .where(SourceDomain.workspace_id == workspace_id)
            )
        ).scalar_one()
    )


def _to_dict(sd: SourceDomain) -> dict:
    total = sd.backlink_count or 0

    def pct(n: int | None) -> float:
        return round((n or 0) * 100.0 / total, 1) if total else 0.0

    return {
        "id": sd.id,
        "domain_key": sd.domain_key,
        "grouping": sd.grouping,
        "backlink_count": sd.backlink_count,
        "indexed_count": sd.indexed_count,
        "not_indexed_count": sd.not_indexed_count,
        "uncertain_count": sd.uncertain_count,
        "unchecked_count": sd.unchecked_count,
        "indexed_pct": pct(sd.indexed_count),
        "not_indexed_pct": pct(sd.not_indexed_count),
        "dofollow_count": sd.dofollow_count,
        "nofollow_count": sd.nofollow_count,
        "dofollow_pct": pct(sd.dofollow_count),
        "duplicate_count": sd.duplicate_count,
        "avg_score": float(sd.avg_score) if sd.avg_score is not None else None,
        "project_count": sd.project_count,
        "user_count": sd.user_count,
        "link_type_distribution": sd.link_type_distribution or {},
        "last_recomputed_at": sd.last_recomputed_at,
        "da": sd.da,
        "pa": sd.pa,
        "spam_score": sd.spam_score,
        "semrush_as": sd.semrush_as,
        "semrush_traffic": sd.semrush_traffic,
        "semrush_keywords": sd.semrush_keywords,
        "domain_age_days": sd.domain_age_days,
        "metrics_updated_at": sd.metrics_updated_at,
    }


async def list_domains(
    db: AsyncSession, ctx: AuthContext, *,
    sort: str = "backlinks", order: str = "desc", search: str | None = None, limit: int = 200,
) -> list[dict]:
    stmt = select(SourceDomain).where(SourceDomain.workspace_id == ctx.workspace_id)
    if search:
        stmt = stmt.where(SourceDomain.domain_key.ilike(f"%{search.strip()}%"))
    col = _SORT_COLUMNS.get(sort, SourceDomain.backlink_count)
    stmt = stmt.order_by(col.asc() if order == "asc" else col.desc()).limit(min(limit, 500))
    return [_to_dict(sd) for sd in (await db.execute(stmt)).scalars().all()]


async def project_view(
    db: AsyncSession, ctx: AuthContext, project_id: uuid.UUID, *, limit: int = 500
) -> dict:
    """Project-wise source-domain usage (Phase 9 P1, owner rule):
    ``used`` — domains this project already has backlinks from (with per-project
    counts); ``available`` — domains known globally in the workspace but NOT yet
    used by this project ("new source domain for this project" candidates)."""
    ctx.assert_project(project_id)
    from sqlalchemy import text as _text

    used_rows = (
        await db.execute(
            _text(
                """
                SELECT b.source_domain AS domain_key,
                       count(*) AS project_links,
                       count(*) FILTER (WHERE b.index_status = 'indexed') AS indexed,
                       round(avg(b.score) FILTER (WHERE b.score IS NOT NULL), 1) AS avg_score,
                       sd.da AS da, sd.backlink_count AS global_links
                FROM backlink_records b
                LEFT JOIN source_domains sd
                  ON sd.workspace_id = b.workspace_id AND sd.domain_key = b.source_domain
                WHERE b.workspace_id = :ws AND b.project_id = :pid AND b.source_domain IS NOT NULL
                GROUP BY b.source_domain, sd.da, sd.backlink_count
                ORDER BY project_links DESC
                LIMIT :lim
                """
            ),
            {"ws": ctx.workspace_id, "pid": project_id, "lim": limit},
        )
    ).mappings().all()

    available_rows = (
        await db.execute(
            _text(
                """
                SELECT sd.domain_key, sd.backlink_count AS global_links, sd.da AS da,
                       sd.project_count, sd.avg_score
                FROM source_domains sd
                WHERE sd.workspace_id = :ws
                  AND NOT EXISTS (
                      SELECT 1 FROM backlink_records b
                      WHERE b.project_id = :pid AND b.source_domain = sd.domain_key
                  )
                ORDER BY sd.backlink_count DESC
                LIMIT :lim
                """
            ),
            {"ws": ctx.workspace_id, "pid": project_id, "lim": limit},
        )
    ).mappings().all()

    return {
        "used": [dict(r) for r in used_rows],
        "available": [dict(r) for r in available_rows],
        "used_count": len(used_rows),
        "available_count": len(available_rows),
    }


async def detail(db: AsyncSession, ctx: AuthContext, domain_id: uuid.UUID) -> dict:
    sd = await db.get(SourceDomain, domain_id)
    if sd is None or sd.workspace_id != ctx.workspace_id:
        raise NotFoundError("Source domain not found")
    rows = (
        await db.execute(
            select(
                BacklinkRecord.id, Project.name, BacklinkRecord.source_page_url,
                BacklinkRecord.target_url, BacklinkRecord.status, BacklinkRecord.score,
                BacklinkRecord.link_type, BacklinkRecord.index_status,
                BacklinkRecord.assigned_user_label,
            )
            .outerjoin(Project, Project.id == BacklinkRecord.project_id)
            .where(BacklinkRecord.source_domain_id == sd.id)
            .order_by(BacklinkRecord.score.desc().nullslast())
            .limit(200)
        )
    ).all()
    backlinks = [
        {
            "id": bid, "project_name": pname, "source_page_url": src, "target_url": tgt,
            "status": status.value if status is not None else None, "score": score,
            "link_type": link_type, "index_status": index_status,
            "assigned_user_label": label,
        }
        for bid, pname, src, tgt, status, score, link_type, index_status, label in rows
    ]
    return {**_to_dict(sd), "backlinks": backlinks}


async def fetch_metrics(
    db: AsyncSession, ctx: AuthContext, *, force: bool = False, limit: int | None = None
) -> int:
    """Fetch + store third-party metrics for the workspace's source domains.

    Processes the highest-traffic stale domains first, capped at
    ``DOMAIN_METRICS_BATCH_LIMIT`` per call (one shared HTTP client). Domain age is
    free (RDAP); Moz/Semrush populate only when their RapidAPI key is configured.
    """
    from datetime import datetime, timedelta, timezone

    import httpx

    from app.integrations import domain_metrics

    cap = limit or settings.DOMAIN_METRICS_BATCH_LIMIT
    stmt = select(SourceDomain).where(SourceDomain.workspace_id == ctx.workspace_id)
    if not force:
        cutoff = datetime.now(timezone.utc) - timedelta(days=settings.DOMAIN_METRICS_REFRESH_DAYS)
        stmt = stmt.where(
            or_(SourceDomain.metrics_updated_at.is_(None), SourceDomain.metrics_updated_at < cutoff)
        )
    stmt = stmt.order_by(SourceDomain.backlink_count.desc()).limit(cap)
    domains = list((await db.execute(stmt)).scalars().all())
    if not domains:
        return 0

    timeout = httpx.Timeout(settings.DOMAIN_METRICS_TIMEOUT_SECONDS)
    async with httpx.AsyncClient(follow_redirects=True, timeout=timeout) as client:
        for sd in domains:
            metrics = await domain_metrics.fetch_all(sd.domain_key, client)
            for field, value in metrics.items():
                setattr(sd, field, value)
    await db.flush()
    return len(domains)
