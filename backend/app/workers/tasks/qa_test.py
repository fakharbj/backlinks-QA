"""Temp QA lab worker (Phase 11) — auto-QA candidate test links, ISOLATED.

Runs the SAME crawl + QA engine as production (proxy escalation, render pool,
relaxed GBP matching, verdict + score) but writes results ONLY to
``qa_test_links``. It never creates BacklinkRecord/CrawlResult, never touches
projects, dashboards, analytics, source_domains, alerts or history. This is a
throwaway space for evaluating a candidate's backlink-building test.
"""

from __future__ import annotations

import asyncio
import dataclasses
import uuid
from datetime import datetime, timezone

from sqlalchemy import func, select
from sqlalchemy.exc import OperationalError

from app.core.config import settings
from app.core.logging import get_logger
from app.crawler.engine import CrawlConfig, CrawlEngine
from app.crawler.types import CrawlRequest
from app.db.session import session_scope
from app.models.qa_test import QATestBatch, QATestLink
from app.qa import evaluate
from app.qa.types import QAPolicy
from app.workers.celery_app import celery_app
from app.workers.runtime import RedisRobotsCache, get_browser, make_rate_limiter, run_async

log = get_logger("worker.qa_test")

_VALID_RELS = ("dofollow", "nofollow", "sponsored", "ugc")


def _build_request(link: QATestLink) -> CrawlRequest:
    rel = (link.expected_rel or "dofollow").strip().lower()
    relaxed_kwargs: dict = {}
    from app.workers.tasks.crawl import _is_relaxed_link_type

    if _is_relaxed_link_type(link.link_type):
        from app.crawler.normalize import normalize_url as _norm
        from app.crawler.relaxed import business_tokens

        tgt = link.target_url or ""
        dom = _norm(tgt).registrable_domain if tgt else ""
        relaxed_kwargs = {
            "relaxed_match": True,
            "business_tokens": business_tokens(dom.split(".")[0] if dom else None),
            "owned_directory_domains": [
                d.strip() for d in settings.OWNED_DIRECTORY_DOMAINS.split(",") if d.strip()
            ],
        }
    return CrawlRequest(
        source_url=link.source_url,
        target_url=link.target_url or "",
        expected_target_url=None,
        expected_anchor_text=link.anchor_text or None,
        expected_rel=rel if rel in _VALID_RELS else "dofollow",
        backlink_id=str(link.id),
        treat_sponsored_as_follow=settings.QA_TREAT_SPONSORED_AS_FOLLOW,
        trailing_slash_policy=settings.QA_TRAILING_SLASH_POLICY,
        # Owner rule: the lab ALWAYS reads the page. These are one-off manual
        # verifications of work a candidate delivered to us — robots.txt must
        # not leave rows stuck at "needs review / robots blocked". The robots
        # fact still shows as an indexability note, it just never blocks the
        # actual link check.
        respect_robots=False,
        allow_render=True,
        # Accuracy-max: when the link is missing, always browser-render and let
        # the proxy clear captchas (Medium/Substack inject body links via JS).
        force_render_on_missing=True,
        **relaxed_kwargs,
    )


def _facts(artifact, result) -> dict:
    """Full per-link evidence for the results table — the SAME depth as the
    production Backlinks drawer: every issue with its code, severity, message
    and fix recommendation, the score breakdown, and why it wasn't scored."""
    issues = []
    for issue in (result.issues or []):
        label = getattr(issue, "label", None)
        issues.append({
            "code": getattr(issue, "code", None),
            "label": getattr(label, "value", None) or (str(label) if label else None),
            "severity": getattr(getattr(issue, "severity", None), "value", None),
            "message": getattr(issue, "message", None),
            "recommendation": getattr(issue, "recommendation", None),
        })
    # Score breakdown ("started at 100, −25 SOURCE_403 → …") — same as the drawer.
    steps = []
    for st in (result.score_breakdown or []):
        steps.append({
            "code": getattr(st, "code", None),
            "delta": getattr(st, "delta", None),
            "note": getattr(st, "note", None),
        })
    return {
        "found_in_raw": result.found_in_raw,
        "found_in_rendered": result.found_in_rendered,
        "rendered": bool(getattr(artifact, "rendered", False)),
        "egress": getattr(artifact, "egress", None),
        "final_url": result.final_url,
        "is_followable": result.is_followable,
        "robots_status": result.robots_status,
        "canonical_status": result.canonical_status,
        "word_count": getattr(getattr(artifact, "signals", None), "word_count", None),
        "issues": issues,
        "recommendations": list(result.recommendations or []),
        "score_breakdown": steps,
        # Why there's no score: we couldn't actually read the page.
        "unverified": bool(result.unverified),
    }


async def _run_async(batch_id_str: str) -> dict:
    batch_id = uuid.UUID(batch_id_str)
    async with session_scope() as s:
        # Only real backlinks are QA'd — competitor references are recorded, not checked.
        links = list(
            (
                await s.execute(
                    select(QATestLink).where(
                        QATestLink.batch_id == batch_id,
                        QATestLink.is_competitor.is_(False),
                    )
                )
            ).scalars().all()
        )
        batch = await s.get(QATestBatch, batch_id)
        if batch is not None:
            batch.status = "running"
        for link in links:
            link.state = "checking"
    if not links:
        # Nothing to QA (e.g. only competitors) — mark done immediately.
        async with session_scope() as s:
            batch = await s.get(QATestBatch, batch_id)
            if batch is not None:
                batch.status = "done"
        return {"processed": 0}

    config = dataclasses.replace(
        CrawlConfig.from_settings(),
        render_enabled=settings.RENDER_ENABLED,
    )
    browser = get_browser() if settings.RENDER_ENABLED else None
    limiter = make_rate_limiter(settings.CRAWL_DEFAULT_RATE_PER_SEC, settings.CRAWL_DEFAULT_BURST)
    engine = CrawlEngine(config, robots_cache=RedisRobotsCache(), browser=browser, rate_limiter=limiter)
    requests = [_build_request(link) for link in links]
    async with engine:
        artifacts = await asyncio.gather(
            *(engine.crawl(req) for req in requests), return_exceptions=True
        )

    policy = QAPolicy.from_settings()
    now = datetime.now(timezone.utc)
    ok = failed = 0
    async with session_scope() as s:
        rows = {
            r.id: r
            for r in (
                await s.execute(select(QATestLink).where(QATestLink.batch_id == batch_id))
            ).scalars().all()
        }
        for link, artifact in zip(links, artifacts):
            row = rows.get(link.id)
            if row is None:
                continue
            if isinstance(artifact, BaseException):
                row.state = "failed"
                row.error = f"QA check failed: {artifact!r}"[:500]
                row.checked_at = now
                failed += 1
                continue
            try:
                artifact.raw_html = artifact.rendered_html = None
                result = evaluate(artifact, policy=policy)
                primary = getattr(artifact, "primary_link", None)
                row.status = result.status.value if result.status else None
                # Owner rule: never auto-score a page we couldn't actually read
                # (hard block / CAPTCHA / JS-only / robots-unread). A number
                # there is misleading — store NULL and let the UI say
                # "Not scored — couldn't check the page".
                row.score = None if result.unverified else result.score
                row.link_found = result.link_found
                row.http_status = result.http_status
                row.current_rel = result.current_rel
                row.current_anchor = (result.current_anchor or None)
                row.indexability = getattr(result.is_indexable, "value", None)
                row.matched_href = getattr(primary, "normalized_url", None)
                top = result.top_issue
                row.top_issue = getattr(getattr(top, "label", None), "value", None) if top else None
                row.facts = _facts(artifact, result)
                row.state = "checked"
                row.error = None
                row.checked_at = now
                ok += 1
            except Exception as exc:  # noqa: BLE001
                row.state = "failed"
                row.error = f"QA evaluation failed: {exc!r}"[:500]
                row.checked_at = now
                failed += 1
        batch = await s.get(QATestBatch, batch_id)
        if batch is not None:
            still = (
                await s.execute(
                    select(func.count()).select_from(QATestLink).where(
                        QATestLink.batch_id == batch_id, QATestLink.state == "checking"
                    )
                )
            ).scalar_one()
            batch.status = "running" if still else "done"
    log.info("qa_test_checked", batch_id=batch_id_str, ok=ok, failed=failed)
    return {"processed": len(links), "ok": ok, "failed": failed}


@celery_app.task(
    name="tasks.qa_test.run_test", bind=True, acks_late=True, max_retries=2,
    autoretry_for=(OperationalError,), retry_backoff=True,
)
def run_test(self, batch_id: str) -> dict:
    return run_async(_run_async(batch_id))
