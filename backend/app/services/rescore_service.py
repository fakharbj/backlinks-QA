"""Re-score existing backlinks under the current rule sets (Phase 8 F17 incr.3).

A scoring-rule change must be applied to already-crawled links WITHOUT re-fetching
them (a re-crawl would perturb verdicts via live network variance). We recompute
from the frozen issue snapshot on the latest ``crawl_results`` row: rebuild the
``Issue`` list, resolve the (now updated) rule set, and re-run ``score_issues`` +
``classify``. ``preview=True`` only tallies what would change; ``preview=False``
writes the new score/status + ``scoring_rule_version_id`` back onto the record.
"""

from __future__ import annotations

import uuid

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import settings
from app.crawler.types import CrawlArtifact, CrawlRequest, FetchError
from app.models.backlink import BacklinkRecord
from app.models.crawl import CrawlResult
from app.models.source_domain import SourceDomain
from app.qa.classification import classify
from app.qa.enums import IssueCategory, IssueLabel, Severity
from app.qa.scoring import score_issues
from app.qa.scoring_rules import metric_bands
from app.qa.types import Issue
from app.services import scoring_config_service


def _issue_from_dict(d: dict) -> Issue | None:
    try:
        return Issue(
            code=d["code"],
            label=IssueLabel(d["label"]),
            category=IssueCategory(d["category"]),
            severity=Severity(d["severity"]),
            message=d.get("message", ""),
            recommendation=d.get("recommendation"),
            evidence=d.get("evidence") or {},
        )
    except (KeyError, ValueError):
        return None  # unknown enum from an older snapshot → skip that issue


def _artifact_from_result(cr: CrawlResult) -> CrawlArtifact:
    """Minimal artifact carrying only what classify() reads (status/content/fetch).
    Detection-based review (captcha/soft-404/conflict) is preserved via the issue
    labels themselves, so this faithfully reproduces the verdict's classification."""
    art = CrawlArtifact(request=CrawlRequest(source_url="", target_url=""))
    art.http_status = cr.http_status
    art.content_type = cr.content_type
    try:
        art.fetch_error = FetchError(cr.fetch_error) if cr.fetch_error else FetchError.NONE
    except ValueError:
        art.fetch_error = FetchError.NONE
    return art


def _signals(
    rec: BacklinkRecord,
    domain_metrics: dict[str, tuple[int | None, int | None, int | None]] | None = None,
) -> dict[str, str]:
    sig: dict[str, str] = {}
    if rec.duplicate_status:
        sig["duplicate"] = "unique" if rec.duplicate_status == "unique" else "duplicate"
    if rec.index_status in ("indexed", "not_indexed"):
        sig["external_index"] = rec.index_status
    # DA / Semrush-AS / age bands from the batch-loaded {domain_key: (da,as,age)}
    # map (avoids an N+1 SourceDomain lookup on a workspace-wide rescore).
    if domain_metrics and rec.source_domain:
        metrics = domain_metrics.get(rec.source_domain)
        if metrics is not None:
            da, semrush_as, age_days = metrics
            sig.update(
                metric_bands(
                    da, semrush_as, age_days,
                    da_high=settings.SCORE_DA_HIGH,
                    da_medium=settings.SCORE_DA_MEDIUM,
                    as_high=settings.SCORE_AS_HIGH,
                    as_medium=settings.SCORE_AS_MEDIUM,
                    age_old_days=settings.SCORE_AGE_OLD_DAYS,
                    age_medium_days=settings.SCORE_AGE_MEDIUM_DAYS,
                )
            )
    return sig


async def _domain_metrics_map(
    db: AsyncSession, workspace_id: uuid.UUID
) -> dict[str, tuple[int | None, int | None, int | None]]:
    """One query: {domain_key: (da, semrush_as, domain_age_days)} for the workspace.

    Loaded up-front so the per-record ``_signals`` call is a dict hit, keeping a
    workspace-wide rescore free of per-row SourceDomain queries (N+1). Only rows
    with at least one metric present are kept — a domain absent from the map emits
    no band signals (identical to today's no-contribution behaviour)."""
    rows = (
        await db.execute(
            select(
                SourceDomain.domain_key,
                SourceDomain.da,
                SourceDomain.semrush_as,
                SourceDomain.domain_age_days,
            ).where(SourceDomain.workspace_id == workspace_id)
        )
    ).all()
    return {
        r.domain_key: (r.da, r.semrush_as, r.domain_age_days)
        for r in rows
        if r.da is not None or r.semrush_as is not None or r.domain_age_days is not None
    }


async def _latest_results_by_backlink(
    db: AsyncSession, records: list[BacklinkRecord]
) -> dict[uuid.UUID, CrawlResult]:
    """Chunk-load the latest crawl result for every record in one query per 500
    ids (records already store ``latest_crawl_result_id`` — no per-row lookups,
    which is what keeps a workspace-wide re-score flat as data grows)."""
    ids = [r.latest_crawl_result_id for r in records if r.latest_crawl_result_id]
    out: dict[uuid.UUID, CrawlResult] = {}
    for i in range(0, len(ids), 500):
        chunk = ids[i : i + 500]
        rows = (
            await db.execute(select(CrawlResult).where(CrawlResult.id.in_(chunk)))
        ).scalars().all()
        for cr in rows:
            out[cr.backlink_id] = cr
    return out


async def rescore(
    db: AsyncSession,
    *,
    workspace_id: uuid.UUID,
    scope: str,
    scope_ref_id: uuid.UUID | None,
    preview: bool = True,
    link_type_id: uuid.UUID | None = None,
) -> dict:
    """Recompute scores for the backlinks a scope governs. Returns a summary
    (total, changed, score_delta_avg, status transitions); writes when not preview."""
    stmt = select(BacklinkRecord).where(
        BacklinkRecord.workspace_id == workspace_id,
        BacklinkRecord.latest_crawl_result_id.is_not(None),
    )
    if scope == "project":
        stmt = stmt.where(BacklinkRecord.project_id == scope_ref_id)
    elif scope == "link_type":
        stmt = stmt.where(BacklinkRecord.link_type_id == scope_ref_id)
    elif scope == "project_link_type":
        stmt = stmt.where(
            BacklinkRecord.project_id == scope_ref_id,
            BacklinkRecord.link_type_id == link_type_id,
        )
    # workspace/global → all of the workspace's crawled backlinks.

    records = (await db.execute(stmt)).scalars().all()

    total = changed = 0
    score_delta_sum = 0
    transitions: dict[str, int] = {}
    latest = await _latest_results_by_backlink(db, list(records))
    domain_metrics = await _domain_metrics_map(db, workspace_id)
    # All records sharing a (project, link_type) resolve to the same rule set —
    # cache it so a large rescore doesn't re-run the scope-chain queries per row.
    ruleset_cache: dict[tuple, object] = {}
    for rec in records:
        cr = latest.get(rec.id)
        if cr is None or not cr.issues:
            continue
        issues = [i for i in (_issue_from_dict(d) for d in cr.issues) if i is not None]
        cache_key = (rec.project_id, rec.link_type_id)
        ruleset = ruleset_cache.get(cache_key)
        if ruleset is None:
            ruleset = await scoring_config_service.resolve(
                db, workspace_id, rec.project_id, rec.link_type_id
            )
            ruleset_cache[cache_key] = ruleset
        score, breakdown = score_issues(
            issues, ruleset=ruleset, signals=_signals(rec, domain_metrics)
        )
        status = classify(_artifact_from_result(cr), issues, score, bands=ruleset.bands)

        total += 1
        if score != (rec.score or 0) or status != rec.status:
            changed += 1
            score_delta_sum += score - (rec.score or 0)
            key = f"{rec.status.value}→{status.value}"
            transitions[key] = transitions.get(key, 0) + 1
        if not preview:
            rec.score = score
            rec.status = status
            rec.scoring_rule_version_id = ruleset.version_id
            # Persist the recomputed breakdown too — otherwise the stored
            # crawl_results.score_breakdown drifts from the displayed score after
            # any ruleset change (the drawer would "explain" a stale number).
            cr.score = score
            cr.status = status
            cr.score_breakdown = [s.to_dict() for s in breakdown]

    if not preview:
        await db.commit()

    return {
        "scope": scope,
        "applied": not preview,
        "total": total,
        "changed": changed,
        "avg_score_delta": round(score_delta_sum / changed, 1) if changed else 0,
        "transitions": transitions,
    }
