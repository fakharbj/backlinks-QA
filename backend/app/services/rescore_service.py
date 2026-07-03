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

from app.crawler.types import CrawlArtifact, CrawlRequest, FetchError
from app.models.backlink import BacklinkRecord
from app.models.crawl import CrawlResult
from app.qa.classification import classify
from app.qa.enums import IssueCategory, IssueLabel, Severity
from app.qa.scoring import score_issues
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


def _signals(rec: BacklinkRecord) -> dict[str, str]:
    sig: dict[str, str] = {}
    if rec.duplicate_status:
        sig["duplicate"] = "unique" if rec.duplicate_status == "unique" else "duplicate"
    if rec.index_status in ("indexed", "not_indexed"):
        sig["external_index"] = rec.index_status
    return sig


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
        score, _ = score_issues(issues, ruleset=ruleset, signals=_signals(rec))
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
