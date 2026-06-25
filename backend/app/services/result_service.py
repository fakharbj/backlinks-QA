"""Persist a crawl + QA verdict and emit change-detection history (PRD §8.10).

Shared by the API single-recheck path and the worker fleet, so a verdict is stored
identically however it was produced. Returns the history events it generated so the
caller can fan them out to alert rules.
"""

from __future__ import annotations

import uuid
from datetime import datetime, timedelta, timezone

from sqlalchemy import delete
from sqlalchemy.ext.asyncio import AsyncSession

from app.crawler.types import CrawlArtifact
from app.models.backlink import BacklinkRecord
from app.models.crawl import BacklinkHistory, BacklinkIssue, CrawlMode, CrawlResult
from app.models.enums import HistoryEventType, Indexability, OverallStatus, RelType, Severity
from app.qa.enums import IssueCategory
from app.qa.types import QAResult


def _now() -> datetime:
    return datetime.now(timezone.utc)


def _redirect_chain(artifact: CrawlArtifact) -> list[dict]:
    return [
        {"url": h.url, "status": h.status, "location": h.location}
        for h in artifact.redirect_chain
    ]


async def persist(
    db: AsyncSession,
    backlink: BacklinkRecord,
    artifact: CrawlArtifact,
    qa: QAResult,
    *,
    crawl_job_id: uuid.UUID | None = None,
    raw_html_key: str | None = None,
    rendered_html_key: str | None = None,
    recheck_interval_hours: int = 24,
    scoring_rule_version_id: uuid.UUID | None = None,
) -> tuple[CrawlResult, list[BacklinkHistory]]:
    crawled_at = artifact.crawled_at or _now()
    primary = artifact.primary_link

    result = CrawlResult(
        crawled_at=crawled_at,
        backlink_id=backlink.id,
        workspace_id=backlink.workspace_id,
        project_id=backlink.project_id,
        crawl_job_id=crawl_job_id,
        crawl_mode=CrawlMode(artifact.crawl_mode.value),
        http_status=artifact.http_status,
        final_url=artifact.final_url,
        content_type=artifact.content_type,
        content_length=artifact.content_length,
        encoding=artifact.encoding,
        response_headers=dict(list(artifact.response_headers.items())[:80]),
        redirect_chain=_redirect_chain(artifact),
        crawl_duration_ms=artifact.crawl_duration_ms,
        fetch_error=artifact.fetch_error.value if artifact.fetch_error.value != "none" else None,
        link_found=qa.link_found,
        found_in_raw=qa.found_in_raw,
        found_in_rendered=qa.found_in_rendered,
        matched_href=primary.normalized_url if primary else None,
        anchor_text=qa.current_anchor,
        rel_values=list(primary.rel) if primary else [],
        link_context=primary.context_text if primary else None,
        link_region=primary.region if primary else None,
        meta_robots=artifact.meta_robots.raw or None,
        x_robots_tag=artifact.x_robots.raw or None,
        canonical_url=artifact.canonical_url,
        robots_allowed=artifact.robots.source_allowed,
        page_title=artifact.signals.title,
        word_count=artifact.signals.word_count,
        language=artifact.signals.language,
        outbound_link_count=artifact.signals.outbound_link_count,
        page_signals={
            "internal_links": artifact.signals.internal_link_count,
            "external_links": artifact.signals.external_link_count,
            "page_bytes": artifact.signals.page_bytes,
            "spam_hits": artifact.signals.spam_keyword_hits,
            "published_date": artifact.signals.published_date,
            "modified_date": artifact.signals.modified_date,
            "date_source": artifact.signals.date_source,
            "egress": artifact.egress,
        },
        status=qa.status,
        score=qa.score,
        score_breakdown=[s.to_dict() for s in qa.score_breakdown],
        is_followable=qa.is_followable,
        is_indexable=qa.is_indexable,
        scoring_rule_version_id=scoring_rule_version_id,
        issues=[i.to_dict() for i in qa.issues],
        recommendations=qa.recommendations,
        raw_html_key=raw_html_key,
        rendered_html_key=rendered_html_key,
    )
    db.add(result)
    await db.flush()

    history = _diff(backlink, qa, result.id, crawled_at)
    for ev in history:
        db.add(ev)

    await _replace_issues(db, backlink, qa, result.id)
    _update_record(backlink, qa, result, recheck_interval_hours)

    return result, history


async def _replace_issues(
    db: AsyncSession, backlink: BacklinkRecord, qa: QAResult, result_id: uuid.UUID
) -> None:
    await db.execute(delete(BacklinkIssue).where(BacklinkIssue.backlink_id == backlink.id))
    for iss in qa.issues:
        if iss.severity is Severity.INFO and iss.label.value == "NONE":
            continue  # don't clutter the current-issue table with pure-INFO notes
        db.add(
            BacklinkIssue(
                backlink_id=backlink.id,
                workspace_id=backlink.workspace_id,
                project_id=backlink.project_id,
                crawl_result_id=result_id,
                code=iss.code,
                label=iss.label.value,
                category=IssueCategory(iss.category.value),
                severity=iss.severity,
                message=iss.message,
                recommendation=iss.recommendation,
                evidence=iss.evidence,
            )
        )


def _update_record(
    backlink: BacklinkRecord, qa: QAResult, result: CrawlResult, interval_hours: int
) -> None:
    backlink.status = qa.status
    backlink.score = qa.score
    backlink.link_found = qa.link_found
    backlink.current_rel = qa.current_rel
    backlink.current_anchor_text = qa.current_anchor
    backlink.http_status = qa.http_status
    backlink.final_url = qa.final_url
    backlink.indexability = qa.is_indexable
    backlink.canonical_status = qa.canonical_status
    backlink.robots_status = qa.robots_status
    backlink.issue_count = len([i for i in qa.issues if i.severity is not Severity.INFO])
    backlink.top_issue_label = qa.top_issue.label.value if qa.top_issue else None
    backlink.latest_crawl_result_id = result.id
    backlink.scoring_rule_version_id = qa.scoring_rule_version_id
    backlink.last_checked_at = result.crawled_at

    if qa.status in (OverallStatus.FAIL, OverallStatus.UNKNOWN):
        backlink.consecutive_failures += 1
    else:
        backlink.consecutive_failures = 0

    # Failing/unknown links are rechecked sooner to confirm/clear the regression.
    factor = 0.25 if qa.status in (OverallStatus.FAIL, OverallStatus.UNKNOWN) else 1.0
    backlink.next_check_at = result.crawled_at + timedelta(hours=interval_hours * factor)


# ── Change detection (PRD §8.10) ─────────────────────────────────────────────────
def _ev(
    backlink: BacklinkRecord,
    result_id: uuid.UUID,
    crawled_at: datetime,
    event_type: HistoryEventType,
    *,
    severity: Severity | None = None,
    field: str | None = None,
    old: object = None,
    new: object = None,
    score_delta: float | None = None,
) -> BacklinkHistory:
    return BacklinkHistory(
        created_at=crawled_at,
        backlink_id=backlink.id,
        workspace_id=backlink.workspace_id,
        project_id=backlink.project_id,
        crawl_result_id=result_id,
        event_type=event_type,
        severity=severity,
        field=field,
        old_value=None if old is None else str(old),
        new_value=None if new is None else str(new),
        score_delta=score_delta,
    )


def _diff(
    backlink: BacklinkRecord, qa: QAResult, result_id: uuid.UUID, crawled_at: datetime
) -> list[BacklinkHistory]:
    events: list[BacklinkHistory] = []

    if backlink.status is OverallStatus.PENDING or backlink.last_checked_at is None:
        events.append(_ev(backlink, result_id, crawled_at, HistoryEventType.FIRST_CRAWL,
                          new=qa.status.value))
        return events

    prev_found = backlink.link_found
    if prev_found is not None and prev_found != qa.link_found:
        events.append(_ev(
            backlink, result_id, crawled_at,
            HistoryEventType.LINK_REMOVED if prev_found else HistoryEventType.LINK_ADDED,
            severity=Severity.CRITICAL if prev_found else Severity.INFO,
            field="link_found", old=prev_found, new=qa.link_found,
        ))

    if backlink.current_rel is not None and qa.current_rel is not None and (
        backlink.current_rel != qa.current_rel
    ):
        downgrade = (
            backlink.current_rel == RelType.DOFOLLOW and qa.current_rel == RelType.NOFOLLOW
        )
        events.append(_ev(backlink, result_id, crawled_at, HistoryEventType.REL_CHANGED,
                          severity=Severity.HIGH if downgrade else Severity.MEDIUM,
                          field="rel", old=backlink.current_rel.value, new=qa.current_rel.value))

    if (backlink.current_anchor_text or "") != (qa.current_anchor or "") and qa.link_found:
        events.append(_ev(backlink, result_id, crawled_at, HistoryEventType.ANCHOR_CHANGED,
                          severity=Severity.MEDIUM, field="anchor",
                          old=backlink.current_anchor_text, new=qa.current_anchor))

    if backlink.indexability is not None and backlink.indexability != qa.is_indexable:
        if qa.is_indexable == Indexability.NOT_INDEXABLE:
            events.append(_ev(backlink, result_id, crawled_at, HistoryEventType.INDEX_TO_NOINDEX,
                              severity=Severity.HIGH, field="indexability",
                              old=backlink.indexability.value, new=qa.is_indexable.value))
        elif backlink.indexability == Indexability.NOT_INDEXABLE and (
            qa.is_indexable == Indexability.INDEXABLE
        ):
            events.append(_ev(backlink, result_id, crawled_at, HistoryEventType.NOINDEX_TO_INDEX,
                              severity=Severity.INFO, field="indexability",
                              old=backlink.indexability.value, new=qa.is_indexable.value))

    if backlink.canonical_status != qa.canonical_status and qa.canonical_status:
        events.append(_ev(backlink, result_id, crawled_at, HistoryEventType.CANONICAL_CHANGED,
                          severity=Severity.MEDIUM, field="canonical_status",
                          old=backlink.canonical_status, new=qa.canonical_status))

    if backlink.http_status is not None and backlink.http_status != qa.http_status:
        events.append(_ev(backlink, result_id, crawled_at, HistoryEventType.STATUS_CODE_CHANGED,
                          severity=Severity.MEDIUM, field="http_status",
                          old=backlink.http_status, new=qa.http_status))

    if backlink.final_url and qa.final_url and backlink.final_url != qa.final_url:
        events.append(_ev(backlink, result_id, crawled_at,
                          HistoryEventType.REDIRECT_TARGET_CHANGED, severity=Severity.LOW,
                          field="final_url", old=backlink.final_url, new=qa.final_url))

    prev_robots = backlink.robots_status
    if prev_robots and prev_robots != qa.robots_status:
        if qa.robots_status == "blocked":
            events.append(_ev(backlink, result_id, crawled_at, HistoryEventType.BECAME_BLOCKED,
                              severity=Severity.HIGH, field="robots_status",
                              old=prev_robots, new=qa.robots_status))
        elif prev_robots == "blocked":
            events.append(_ev(backlink, result_id, crawled_at, HistoryEventType.BECAME_ACCESSIBLE,
                              severity=Severity.INFO, field="robots_status",
                              old=prev_robots, new=qa.robots_status))

    if backlink.score is not None and backlink.score != qa.score:
        events.append(_ev(backlink, result_id, crawled_at, HistoryEventType.SCORE_CHANGED,
                          severity=Severity.LOW, field="score",
                          old=backlink.score, new=qa.score,
                          score_delta=float(qa.score - backlink.score)))

    return events
