"""Staged QA checks for review batches (0029).

Runs the SAME crawl + QA engine as production checks (proxy escalation, render
pool, markdown/redirect matching, verdict + score) for the links of a
``link_review`` batch — but persists everything into ``batch_items.payload``
only. No BacklinkRecord, no CrawlResult, no alerts, no history: the production
knowledge base stays untouched until the user approves the items.
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
from app.models.batch import Batch, BatchItem
from app.qa import evaluate
from app.qa.types import QAPolicy
from app.services import batch_service, qa_settings_service, scoring_config_service
from app.workers.celery_app import celery_app
from app.workers.runtime import RedisRobotsCache, get_browser, make_rate_limiter, run_async

log = get_logger("worker.staging")

_VALID_RELS = ("dofollow", "nofollow", "sponsored", "ugc")


def _build_request(item: BatchItem) -> CrawlRequest:
    mapped = (item.payload or {}).get("mapped") or {}
    rel = (mapped.get("expected_rel") or "dofollow").strip().lower()
    # Relaxed GBP/citation matching for staged rows too (same owner rule as the
    # main crawl path) — link type from the mapped row, business tokens derived
    # from the target domain's label (no project loaded in this isolated path).
    relaxed_kwargs: dict = {}
    from app.workers.tasks.crawl import _is_relaxed_link_type

    if _is_relaxed_link_type(mapped.get("link_type")):
        from app.crawler.normalize import normalize_url as _norm
        from app.crawler.relaxed import business_tokens

        tgt = mapped.get("target_url") or ""
        dom = _norm(tgt).registrable_domain if tgt else ""
        relaxed_kwargs = {
            "relaxed_match": True,
            "business_tokens": business_tokens(dom.split(".")[0] if dom else None),
            "owned_directory_domains": [
                d.strip() for d in settings.OWNED_DIRECTORY_DOMAINS.split(",") if d.strip()
            ],
        }
    return CrawlRequest(
        source_url=mapped.get("source_page_url") or item.label,
        target_url=mapped.get("target_url") or "",
        expected_target_url=mapped.get("expected_target_url") or None,
        expected_anchor_text=mapped.get("expected_anchor_text") or None,
        expected_rel=rel if rel in _VALID_RELS else "dofollow",
        backlink_id=str(item.id),
        treat_sponsored_as_follow=settings.QA_TREAT_SPONSORED_AS_FOLLOW,
        trailing_slash_policy=settings.QA_TRAILING_SLASH_POLICY,
        respect_robots=settings.CRAWL_RESPECT_ROBOTS,
        allow_render=True,
        **relaxed_kwargs,
    )


def _qa_payload(artifact, result) -> dict:
    """Flatten the artifact + QAResult into the JSON the Batch Details UI
    renders — same facts the main QA stores, minus the HTML snapshots."""
    primary = getattr(artifact, "primary_link", None)
    issues = []
    for issue in (result.issues or [])[:8]:
        label = getattr(issue, "label", None)
        issues.append(
            {
                "code": getattr(issue, "code", None),
                "label": getattr(label, "value", None) or (str(label) if label else None),
                "severity": getattr(getattr(issue, "severity", None), "value", None),
                "message": getattr(issue, "message", None),
            }
        )
    top = result.top_issue
    top_label = getattr(getattr(top, "label", None), "value", None) if top else None
    return {
        "status": result.status.value if result.status else None,
        "score": result.score,
        "link_found": result.link_found,
        "found_in_raw": result.found_in_raw,
        "found_in_rendered": result.found_in_rendered,
        "rendered": bool(getattr(artifact, "rendered", False)),
        "http_status": result.http_status,
        "final_url": result.final_url,
        "anchor": result.current_anchor,
        "rel": result.current_rel,
        "matched_href": getattr(primary, "normalized_url", None),
        "is_followable": result.is_followable,
        "indexability": getattr(result.is_indexable, "value", None),
        "robots_status": result.robots_status,
        "canonical_status": result.canonical_status,
        "top_issue": top_label,
        "issues": issues,
        "word_count": getattr(getattr(artifact, "signals", None), "word_count", None),
        "checked_at": datetime.now(timezone.utc).isoformat(),
    }


async def _check_staged_links_async(batch_id_str: str, item_ids: list[str]) -> dict:
    batch_id = uuid.UUID(batch_id_str)
    uuids = [uuid.UUID(i) for i in item_ids]

    # 1) Load the staged rows + the batch's workspace-scoped QA settings in a
    #    short session (no session held during network IO).
    async with session_scope() as s:
        items = list(
            (
                await s.execute(
                    select(BatchItem).where(
                        BatchItem.id.in_(uuids), BatchItem.batch_id == batch_id
                    )
                )
            ).scalars().all()
        )
        batch_row = await s.get(Batch, batch_id)
        qa_cfg = (
            await qa_settings_service.get_effective(s, batch_row.workspace_id)
            if batch_row is not None
            else qa_settings_service.defaults()
        )
    if not items:
        return {"processed": 0}

    # Real-time log the moment the check starts so the batch is never "empty".
    await batch_service.add_log(
        batch_id,
        f"Starting QA on {len(items)} staged link(s) — "
        f"timeout {qa_cfg['total_timeout']:g}s, "
        f"render {'on' if qa_cfg['render_enabled'] else 'off'}, "
        f"rate {qa_cfg['rate_per_sec']:g}/s per domain.",
    )

    # 2) Same engine as production crawls, with this workspace's QA overrides
    #    applied on top of the config defaults; browser renders JS pages inline
    #    when render is enabled.
    browser = get_browser() if qa_cfg["render_enabled"] else None
    config = dataclasses.replace(
        CrawlConfig.from_settings(),
        connect_timeout=qa_cfg["connect_timeout"],
        read_timeout=qa_cfg["read_timeout"],
        total_timeout=qa_cfg["total_timeout"],
        render_enabled=qa_cfg["render_enabled"],
        render_timeout_ms=qa_cfg["render_timeout_ms"],
        render_wait_until=qa_cfg["render_wait_until"],
    )
    limiter = make_rate_limiter(qa_cfg["rate_per_sec"], qa_cfg["burst"])
    engine = CrawlEngine(
        config, robots_cache=RedisRobotsCache(), browser=browser, rate_limiter=limiter
    )
    requests = [_build_request(it) for it in items]
    async with engine:
        artifacts = await asyncio.gather(
            *(engine.crawl(req) for req in requests), return_exceptions=True
        )

    policy = QAPolicy.from_settings()
    now = datetime.now(timezone.utc)
    ok = failed = 0

    # 3) Persist verdicts into the items only.
    async with session_scope() as s:
        rows = {
            it.id: it
            for it in (
                await s.execute(select(BatchItem).where(BatchItem.id.in_(uuids)))
            ).scalars().all()
        }
        # Ruleset parity with production crawls: without it, staged previews use
        # the legacy severity deductions and their scores diverge from what the
        # same links get after approve. Resolved once per batch (project scope;
        # link-type-scoped overrides are rare enough to ignore here). Fail-open.
        stage_batch = await s.get(Batch, batch_id)
        ruleset = None
        if stage_batch is not None:
            try:
                ruleset = await scoring_config_service.resolve(
                    s, stage_batch.workspace_id, stage_batch.project_id, None
                )
            except Exception:  # noqa: BLE001 — preview must not die on config
                ruleset = None
        for item, artifact in zip(items, artifacts):
            row = rows.get(item.id)
            if row is None:
                continue
            if isinstance(artifact, BaseException):
                row.state = "failed"
                row.error = f"QA check failed: {artifact!r}"[:500]
                row.checked_at = now
                failed += 1
                continue
            try:
                artifact.raw_html = artifact.rendered_html = None  # free memory
                result = evaluate(artifact, policy=policy, ruleset=ruleset)
                payload = dict(row.payload or {})
                payload["qa"] = _qa_payload(artifact, result)
                row.payload = payload
                row.state = "checked"
                row.error = None
                row.checked_at = now
                ok += 1
            except Exception as exc:  # noqa: BLE001 — isolate one bad row
                row.state = "failed"
                row.error = f"QA evaluation failed: {exc!r}"[:500]
                row.checked_at = now
                failed += 1

        # 4) Batch progress: back to "review" once nothing is left checking.
        batch = await s.get(Batch, batch_id)
        if batch is not None:
            # Derive counters from the terminal item states (NOT +=) so a Celery
            # redelivery of this task can't double-count (acks_late + autoretry).
            checked_total = (
                await s.execute(
                    select(func.count()).select_from(BatchItem).where(
                        BatchItem.batch_id == batch_id, BatchItem.state == "checked"
                    )
                )
            ).scalar_one()
            failed_total = (
                await s.execute(
                    select(func.count()).select_from(BatchItem).where(
                        BatchItem.batch_id == batch_id, BatchItem.state == "failed"
                    )
                )
            ).scalar_one()
            counters = dict(batch.counters or {})
            counters["checked"] = int(checked_total)
            if failed_total:
                counters["check_failed"] = int(failed_total)
            batch.counters = counters
            still_checking = (
                await s.execute(
                    select(func.count()).select_from(BatchItem).where(
                        BatchItem.batch_id == batch_id, BatchItem.state == "checking"
                    )
                )
            ).scalar_one()
            if still_checking:
                batch.meta = {
                    **(batch.meta or {}),
                    "current_step": f"QA-checking… {still_checking} links left",
                }
            else:
                batch.status = "review"
                batch.meta = {**(batch.meta or {}), "current_step": ""}

    if ok or failed:
        await batch_service.add_log(
            batch_id,
            f"QA-checked {ok} staged links" + (f" ({failed} failed to check)" if failed else "")
            + " — verdicts are stored in this batch only.",
            level="warn" if failed else "info",
        )
    return {"processed": len(items), "ok": ok, "failed": failed}


@celery_app.task(
    name="tasks.staging.check_staged_links",
    bind=True,
    acks_late=True,
    max_retries=3,
    autoretry_for=(OperationalError,),
    retry_backoff=True,
)
def check_staged_links(self, batch_id: str, item_ids: list[str]) -> dict:
    return run_async(_check_staged_links_async(batch_id, item_ids))
