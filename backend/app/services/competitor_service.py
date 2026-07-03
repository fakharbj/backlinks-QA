"""Competitor backlink ingest + gap analysis (Phase 8).

Ingest a competitor's link list (paste/CSV), canonicalise each URL with the SAME
identity system as our own backlinks, then roll up by registrable source domain and
compare against the project's own links: a competitor domain we don't link from is
a NEW_OPPORTUNITY; one we already use is EXISTING. Fully recomputed on each ingest
so the comparison is always consistent with current data.
"""

from __future__ import annotations

import uuid

from sqlalchemy import bindparam, delete, select, text
from sqlalchemy.dialects.postgresql import UUID as PGUUID
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.deps import AuthContext
from app.core.errors import NotFoundError, ValidationAppError
from app.crawler.normalize import normalize_url
from app.models.competitor import (
    CompetitorBacklink,
    CompetitorDomainDecision,
    CompetitorSheet,
    CompetitorSourceDomain,
)
from app.models.project import Project
from app.services import canonical_service


async def _ensure_project(db: AsyncSession, ctx: AuthContext, project_id: uuid.UUID) -> None:
    """Validate the project belongs to the caller's workspace (assert_project is a
    no-op for unrestricted admins, so we must check ownership explicitly — mirrors
    project_settings_service._ensure_project)."""
    project = await db.get(Project, project_id)
    if project is None or project.workspace_id != ctx.workspace_id:
        raise NotFoundError("Project not found")
    ctx.assert_project(project_id)


def _parse_rows(raw_text: str) -> list[tuple[str, str | None, str | None, str | None]]:
    """Parse pasted text → [(url, anchor, rel, link_type)]. One URL per line,
    optionally followed by comma/tab-separated anchor, rel and link type
    (e.g. "…, brand anchor, dofollow, Guest Post"). Header-ish lines skipped."""
    rows: list[tuple[str, str | None, str | None, str | None]] = []
    for line in raw_text.splitlines():
        line = line.strip()
        if not line:
            continue
        parts = [p.strip() for p in (line.split("\t") if "\t" in line else line.split(","))]
        url = parts[0].strip().strip('"')
        if not url or url.lower() in ("url", "source url", "source_url", "backlink"):
            continue
        if not (url.startswith("http://") or url.startswith("https://")):
            url = "https://" + url
        anchor = parts[1] if len(parts) > 1 and parts[1] else None
        rel = parts[2] if len(parts) > 2 and parts[2] else None
        link_type = parts[3] if len(parts) > 3 and parts[3] else None
        rows.append((url, anchor, rel, link_type))
    return rows


async def ingest(
    db: AsyncSession,
    ctx: AuthContext,
    *,
    project_id: uuid.UUID,
    name: str,
    raw_text: str,
) -> CompetitorSheet:
    await _ensure_project(db, ctx, project_id)
    parsed = _parse_rows(raw_text)
    if not parsed:
        raise ValidationAppError("No competitor URLs found. Paste one source URL per line.")

    sheet = CompetitorSheet(
        workspace_id=ctx.workspace_id, project_id=project_id, name=name[:200] or "Competitor upload",
        source_kind="paste", status="ready", total_rows=len(parsed), created_by=ctx.user.id,
    )
    db.add(sheet)
    await db.flush()

    cache: dict[str, uuid.UUID] = {}
    for url, anchor, rel, link_type in parsed:
        parsed_url = normalize_url(url)
        domain = parsed_url.registrable_domain if parsed_url.valid else None
        canonical = await canonical_service.resolve_canonical(db, url, cache=cache)
        db.add(
            CompetitorBacklink(
                workspace_id=ctx.workspace_id, project_id=project_id, competitor_sheet_id=sheet.id,
                canonical_url_id=canonical.id if canonical else None,
                raw_url=url[:2048], source_domain=domain, anchor=anchor, rel=rel,
                link_type_label=(link_type or None) and str(link_type)[:120],
            )
        )
    await db.flush()

    counts = await recompute_domains(db, ctx.workspace_id, project_id, sheet_id=sheet.id)
    sheet.domain_count = counts["domains"]
    sheet.new_domains = counts["new"]
    sheet.existing_domains = counts["existing"]
    await db.flush()
    return sheet


async def recompute_domains(
    db: AsyncSession, workspace_id: uuid.UUID, project_id: uuid.UUID, *, sheet_id: uuid.UUID | None = None
) -> dict:
    """Rebuild the per-domain comparison for a project from all its competitor links."""
    await db.execute(
        delete(CompetitorSourceDomain).where(
            CompetitorSourceDomain.workspace_id == workspace_id,
            CompetitorSourceDomain.project_id == project_id,
        )
    )
    await db.execute(
        text(
            """
            WITH comp AS (
                SELECT source_domain AS domain_key, count(*) AS url_count
                FROM competitor_backlinks
                WHERE workspace_id = :ws AND project_id = :pid AND source_domain IS NOT NULL
                GROUP BY source_domain
            ),
            ours AS (
                SELECT source_domain AS domain_key, count(*) AS cnt,
                       round(100.0 * count(*) FILTER (WHERE index_status = 'indexed')
                             / nullif(count(*), 0), 1) AS indexed_pct
                FROM backlink_records
                WHERE workspace_id = :ws AND project_id = :pid AND source_domain IS NOT NULL
                GROUP BY source_domain
            )
            INSERT INTO competitor_source_domains
                (id, workspace_id, project_id, competitor_sheet_id, domain_key, url_count,
                 category, our_link_count, our_indexed_pct, is_new, last_recomputed_at,
                 created_at, updated_at)
            SELECT gen_random_uuid(), :ws, :pid, :sheet, comp.domain_key, comp.url_count,
                   CASE WHEN coalesce(ours.cnt, 0) > 0 THEN 'existing' ELSE 'new_opportunity' END,
                   coalesce(ours.cnt, 0), ours.indexed_pct, (coalesce(ours.cnt, 0) = 0),
                   now(), now(), now()
            FROM comp LEFT JOIN ours USING (domain_key)
            """
        ),
        {"ws": workspace_id, "pid": project_id, "sheet": sheet_id},
    )
    await db.flush()

    row = (
        await db.execute(
            text(
                """
                SELECT count(*) AS domains,
                       count(*) FILTER (WHERE category = 'new_opportunity') AS new,
                       count(*) FILTER (WHERE category = 'existing') AS existing
                FROM competitor_source_domains WHERE workspace_id = :ws AND project_id = :pid
                """
            ),
            {"ws": workspace_id, "pid": project_id},
        )
    ).mappings().first() or {}
    return {"domains": row.get("domains", 0), "new": row.get("new", 0), "existing": row.get("existing", 0)}


async def delete_sheet(db: AsyncSession, ctx: AuthContext, sheet_id: uuid.UUID) -> str:
    """Delete one competitor upload and its links, then rebuild the domain
    comparison so opportunity counts stay truthful. Returns the sheet name."""
    sheet = await db.get(CompetitorSheet, sheet_id)
    if sheet is None or sheet.workspace_id != ctx.workspace_id:
        raise NotFoundError("Competitor upload not found")
    await _ensure_project(db, ctx, sheet.project_id)
    name, project_id = sheet.name, sheet.project_id
    await db.execute(
        delete(CompetitorBacklink).where(CompetitorBacklink.competitor_sheet_id == sheet_id)
    )
    await db.delete(sheet)
    await db.flush()
    await recompute_domains(db, ctx.workspace_id, project_id)
    return name


async def list_sheets(db: AsyncSession, ctx: AuthContext, project_id: uuid.UUID) -> list[CompetitorSheet]:
    await _ensure_project(db, ctx, project_id)
    return list(
        (
            await db.execute(
                select(CompetitorSheet)
                .where(CompetitorSheet.workspace_id == ctx.workspace_id, CompetitorSheet.project_id == project_id)
                .order_by(CompetitorSheet.created_at.desc())
            )
        ).scalars().all()
    )


async def list_domains(
    db: AsyncSession,
    ctx: AuthContext,
    project_id: uuid.UUID,
    *,
    category: str | None = None,
    include_dismissed: bool = True,
    exclude_guest_posts: bool = False,
    limit: int = 500,
) -> list[dict]:
    """Domain rows + manual decision + guest-post tag. 'Used' is derived live
    (category = existing); manual dismissals survive recomputes via the
    decisions table."""
    await _ensure_project(db, ctx, project_id)
    conds = ["d.workspace_id = :ws", "d.project_id = :pid"]
    if category in ("existing", "new_opportunity"):
        conds.append("d.category = :cat")
    if not include_dismissed:
        conds.append("coalesce(dec.status, 'open') <> 'dismissed'")
    if exclude_guest_posts:
        conds.append(
            "NOT EXISTS (SELECT 1 FROM competitor_backlinks g WHERE g.project_id = d.project_id "
            "AND g.source_domain = d.domain_key AND g.link_type_label ILIKE '%guest%')"
        )
    sql = text(
        f"""
        SELECT d.id::text AS id, d.domain_key, d.url_count, d.category,
               d.our_link_count, d.our_indexed_pct, d.is_new,
               coalesce(d.da, sd.da) AS da, coalesce(d.pa, sd.pa) AS pa,
               coalesce(dec.status, 'open') AS decision,
               dec.reason AS decision_reason,
               EXISTS (
                 SELECT 1 FROM competitor_backlinks cb
                 WHERE cb.project_id = d.project_id AND cb.source_domain = d.domain_key
                   AND cb.link_type_label ILIKE '%guest%'
               ) AS has_guest_post
        FROM competitor_source_domains d
        LEFT JOIN competitor_domain_decisions dec
          ON dec.workspace_id = d.workspace_id AND dec.project_id = d.project_id
         AND dec.domain_key = d.domain_key
        LEFT JOIN source_domains sd
          ON sd.workspace_id = d.workspace_id AND sd.domain_key = d.domain_key
        WHERE {' AND '.join(conds)}
        ORDER BY d.category ASC, d.url_count DESC
        LIMIT :lim
        """
    )
    params: dict = {"ws": ctx.workspace_id, "pid": project_id, "lim": max(1, min(limit, 2000))}
    if category in ("existing", "new_opportunity"):
        params["cat"] = category
    rows = (await db.execute(sql, params)).mappings().all()
    return [dict(r) for r in rows]


async def decide(
    db: AsyncSession,
    ctx: AuthContext,
    project_id: uuid.UUID,
    domain_key: str,
    *,
    status: str,
    reason: str | None = None,
) -> None:
    """Record a manual opportunity decision: 'dismissed' hides it from the active
    list; 'open' re-opens it. Upsert so recomputes never lose it."""
    from datetime import datetime, timezone

    from sqlalchemy.dialects.postgresql import insert as pg_insert

    await _ensure_project(db, ctx, project_id)
    if status not in ("dismissed", "open"):
        raise ValidationAppError("Decision must be 'dismissed' or 'open'.")
    stmt = (
        pg_insert(CompetitorDomainDecision)
        .values(
            workspace_id=ctx.workspace_id, project_id=project_id,
            domain_key=domain_key.lower()[:255], status=status,
            reason=(reason or "")[:300] or None, decided_by=ctx.user.id,
            decided_at=datetime.now(timezone.utc),
        )
        .on_conflict_do_update(
            constraint="uq_comp_domain_decision",
            set_={
                "status": status,
                "reason": (reason or "")[:300] or None,
                "decided_by": ctx.user.id,
                "decided_at": datetime.now(timezone.utc),
            },
        )
    )
    await db.execute(stmt)
    await db.flush()


async def check_metrics(
    db: AsyncSession, ctx: AuthContext, project_id: uuid.UUID,
    *, freshness_days: int = 10, limit: int = 100, force: bool = False,
) -> dict:
    """Fill DA/PA for this project's competitor domains, REUSE-FIRST:
    1. copy from ``source_domains`` when we already checked that domain recently
       (zero API cost); 2. skip domains checked within the freshness window;
    3. only then call the metrics API. Every step is recorded (batch + history)."""
    import httpx as _httpx
    from datetime import datetime, timedelta, timezone

    from app.integrations import domain_metrics as dm_integration
    from app.models.metric_history import MetricCheckHistory
    from app.services import batch_service

    await _ensure_project(db, ctx, project_id)
    cutoff = datetime.now(timezone.utc) - timedelta(days=max(1, freshness_days))

    rows = (
        await db.execute(
            select(CompetitorSourceDomain)
            .where(
                CompetitorSourceDomain.workspace_id == ctx.workspace_id,
                CompetitorSourceDomain.project_id == project_id,
            )
            .order_by(CompetitorSourceDomain.da.is_(None).desc(), CompetitorSourceDomain.url_count.desc())
            .limit(max(1, min(limit, 500)))
        )
    ).scalars().all()
    if not rows:
        return {"checked": 0, "from_cache": 0, "api_calls": 0, "skipped_fresh": 0}

    batch_id = await batch_service.start(
        "competitor_check", ctx.workspace_id, project_id=project_id,
        label=f"Competitor metrics check ({len(rows)} domains)", started_by=ctx.user.id,
        total=len(rows),
    )

    # Our own source-domain metrics (already paid for) → free reuse.
    from sqlalchemy import String as _String
    from sqlalchemy import bindparam as _bindparam
    from sqlalchemy.dialects.postgresql import ARRAY as _ARRAY

    sd_stmt = text(
        "SELECT domain_key, da, pa, metrics_updated_at FROM source_domains "
        "WHERE workspace_id = :ws AND domain_key = ANY(:keys)"
    ).bindparams(_bindparam("keys", type_=_ARRAY(_String())))
    sd_map = {
        r["domain_key"]: r
        for r in (
            await db.execute(sd_stmt, {"ws": ctx.workspace_id, "keys": [r.domain_key for r in rows]})
        ).mappings().all()
    }

    checked = cached = api_calls = skipped = 0
    async with _httpx.AsyncClient(timeout=20) as client:
        for row in rows:
            if not force and row.da is not None and row.updated_at and row.updated_at >= cutoff:
                skipped += 1
                continue
            sd = sd_map.get(row.domain_key)
            if (
                not force and sd and sd["da"] is not None
                and sd["metrics_updated_at"] and sd["metrics_updated_at"] >= cutoff
            ):
                row.da = sd["da"]
                row.pa = sd["pa"]
                cached += 1
                checked += 1
                db.add(MetricCheckHistory(
                    workspace_id=ctx.workspace_id, entity_kind="domain",
                    entity_key=row.domain_key[:600], provider="moz", from_cache=True,
                    ok=True, batch_id=batch_id,
                ))
                continue
            try:
                data = await dm_integration.fetch_all(row.domain_key, client)
            except Exception:  # noqa: BLE001 — one bad domain must not stop the run
                data = {}
            if data.get("da") is not None:
                row.da = data.get("da")
                row.pa = data.get("pa")
            api_calls += 1
            checked += 1
            db.add(MetricCheckHistory(
                workspace_id=ctx.workspace_id, entity_kind="domain",
                entity_key=row.domain_key[:600], provider="moz", from_cache=False,
                ok=bool(data), batch_id=batch_id,
            ))
    await db.flush()

    await batch_service.update(
        batch_id,
        totals={"total": len(rows), "done": len(rows), "ok": checked, "skipped": skipped},
        counters_inc={"api_calls": api_calls, "api_cached": cached},
    )
    await batch_service.add_log(
        batch_id,
        f"{checked} domain(s) updated — {cached} reused from our own recent checks (no API cost), "
        f"{api_calls} fresh API call(s), {skipped} already fresh (checked within {freshness_days} days).",
    )
    await batch_service.finish(batch_id)
    return {"checked": checked, "from_cache": cached, "api_calls": api_calls, "skipped_fresh": skipped}


async def summary(db: AsyncSession, ctx: AuthContext, project_id: uuid.UUID) -> dict:
    await _ensure_project(db, ctx, project_id)
    row = (
        await db.execute(
            text(
                """
                SELECT count(*) AS domains,
                       count(*) FILTER (
                           WHERE d.category = 'new_opportunity'
                             AND coalesce(dec.status, 'open') <> 'dismissed'
                       ) AS new_opportunities,
                       count(*) FILTER (WHERE d.category = 'existing') AS existing,
                       count(*) FILTER (WHERE coalesce(dec.status, 'open') = 'dismissed') AS dismissed,
                       coalesce(sum(d.url_count), 0) AS competitor_links
                FROM competitor_source_domains d
                LEFT JOIN competitor_domain_decisions dec
                  ON dec.workspace_id = d.workspace_id AND dec.project_id = d.project_id
                 AND dec.domain_key = d.domain_key
                WHERE d.workspace_id = :ws AND d.project_id = :pid
                """
            ),
            {"ws": ctx.workspace_id, "pid": project_id},
        )
    ).mappings().first() or {}
    return dict(row)
