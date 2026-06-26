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
from app.models.competitor import CompetitorBacklink, CompetitorSheet, CompetitorSourceDomain
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


def _parse_rows(raw_text: str) -> list[tuple[str, str | None, str | None]]:
    """Parse pasted text → [(url, anchor, rel)]. Accepts one URL per line, optionally
    followed by a comma/tab-separated anchor and rel. Header-ish lines are skipped."""
    rows: list[tuple[str, str | None, str | None]] = []
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
        rows.append((url, anchor, rel))
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
    for url, anchor, rel in parsed:
        parsed_url = normalize_url(url)
        domain = parsed_url.registrable_domain if parsed_url.valid else None
        canonical = await canonical_service.resolve_canonical(db, url, cache=cache)
        db.add(
            CompetitorBacklink(
                workspace_id=ctx.workspace_id, project_id=project_id, competitor_sheet_id=sheet.id,
                canonical_url_id=canonical.id if canonical else None,
                raw_url=url[:2048], source_domain=domain, anchor=anchor, rel=rel,
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
    db: AsyncSession, ctx: AuthContext, project_id: uuid.UUID, *, category: str | None = None, limit: int = 500
) -> list[CompetitorSourceDomain]:
    await _ensure_project(db, ctx, project_id)
    stmt = select(CompetitorSourceDomain).where(
        CompetitorSourceDomain.workspace_id == ctx.workspace_id,
        CompetitorSourceDomain.project_id == project_id,
    )
    if category in ("existing", "new_opportunity"):
        stmt = stmt.where(CompetitorSourceDomain.category == category)
    stmt = stmt.order_by(
        CompetitorSourceDomain.category.asc(), CompetitorSourceDomain.url_count.desc()
    ).limit(limit)
    return list((await db.execute(stmt)).scalars().all())


async def summary(db: AsyncSession, ctx: AuthContext, project_id: uuid.UUID) -> dict:
    await _ensure_project(db, ctx, project_id)
    row = (
        await db.execute(
            text(
                """
                SELECT count(*) AS domains,
                       count(*) FILTER (WHERE category = 'new_opportunity') AS new_opportunities,
                       count(*) FILTER (WHERE category = 'existing') AS existing,
                       coalesce(sum(url_count), 0) AS competitor_links
                FROM competitor_source_domains WHERE workspace_id = :ws AND project_id = :pid
                """
            ),
            {"ws": ctx.workspace_id, "pid": project_id},
        )
    ).mappings().first() or {}
    return dict(row)
