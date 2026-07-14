"""Batch crawl tasks (Arch §5.2).

A task receives a *batch* of backlink ids and runs them concurrently inside one
event loop with a shared engine (httpx client + Redis token bucket). DB sessions
are **not** held during network I/O: records are loaded up-front, crawled with no
session open, then persisted one-by-one (each its own transaction → partial-result
safe, PRD §9.3). ``acks_late`` + idempotent writes make a crashed batch safe to rerun.
"""

from __future__ import annotations

import asyncio
import uuid

from sqlalchemy import select, update
from sqlalchemy.exc import OperationalError

from app.core.config import settings
from app.core.logging import get_logger
from app.core.metrics import CRAWL_TOTAL, QA_VERDICTS
from app.crawler.engine import CrawlConfig, CrawlEngine
from app.crawler.types import CrawlRequest
from app.db.session import session_scope
from app.integrations import storage
from app.models.backlink import BacklinkRecord
from app.models.crawl import CrawlJob
from app.models.enums import JobStatus, OverallStatus, ScheduleInterval
from app.models.project import Project
from app.models.source_domain import SourceDomain
from app.qa import evaluate
from app.qa.scoring_rules import metric_bands
from app.qa.types import QAPolicy
from app.services import alert_service, result_service, scoring_config_service
from app.workers.celery_app import celery_app
from app.workers.runtime import RedisRobotsCache, get_browser, make_rate_limiter, run_async

log = get_logger("worker.crawl")


def _scoring_signals(
    record: BacklinkRecord, source_domain: SourceDomain | None = None
) -> dict[str, str]:
    """Metric-parameter values for the scorer.

    Always emits duplicate / external-index from the record. When the source
    domain's aggregate row is supplied, also emits the DA / Semrush-AS / domain-age
    bands (one signal per metric that is actually present). Bands are computed from
    the configured cutoffs; each contributes 0 unless a rule set assigns points."""
    signals: dict[str, str] = {}
    dup = record.duplicate_status
    if dup:
        signals["duplicate"] = "unique" if dup == "unique" else "duplicate"
    idx = record.index_status
    if idx in ("indexed", "not_indexed"):
        signals["external_index"] = idx
    if source_domain is not None:
        signals.update(
            metric_bands(
                source_domain.da,
                source_domain.semrush_as,
                source_domain.domain_age_days,
                da_high=settings.SCORE_DA_HIGH,
                da_medium=settings.SCORE_DA_MEDIUM,
                as_high=settings.SCORE_AS_HIGH,
                as_medium=settings.SCORE_AS_MEDIUM,
                age_old_days=settings.SCORE_AGE_OLD_DAYS,
                age_medium_days=settings.SCORE_AGE_MEDIUM_DAYS,
            )
        )
    return signals

_INTERVAL_HOURS = {
    ScheduleInterval.DAILY: 24,
    ScheduleInterval.WEEKLY: 24 * 7,
    ScheduleInterval.MONTHLY: 24 * 30,
    ScheduleInterval.MANUAL: settings.DEFAULT_RECHECK_INTERVAL_HOURS,
}


def _is_relaxed_link_type(link_type: str | None) -> bool:
    """Owner rule: link types whose NAME contains gbp/gmb (configurable) get the
    relaxed GBP/citation matcher. Matched on the denormalized name string —
    same convention as the GBP dedup exclusion."""
    if not settings.RELAXED_MATCH_ENABLED or not link_type:
        return False
    low = link_type.lower()
    return any(
        s.strip() and s.strip() in low
        for s in settings.RELAXED_MATCH_LINK_TYPE_SUBSTRINGS.lower().split(",")
    )


def _relaxed_fields(record: BacklinkRecord, project: Project | None) -> dict:
    """CrawlRequest kwargs for the relaxed GBP/citation matcher (empty when the
    link type doesn't qualify). Business identity = per-project business name +
    aliases (crawl_settings JSONB) with project name + target-domain label as
    the fallback, stoplist-guarded in crawler.relaxed."""
    if not _is_relaxed_link_type(record.link_type):
        return {}
    from app.crawler.relaxed import business_tokens

    cs = (project.crawl_settings or {}) if project else {}
    aliases = cs.get("business_aliases") or []
    dom_label = ""
    if project and project.target_domain:
        dom_label = project.target_domain.split(".")[0]
    tokens = business_tokens(
        cs.get("business_name"),
        *[a for a in aliases if isinstance(a, str)],
        project.name if project else None,
        dom_label,
    )
    return {
        "relaxed_match": True,
        "business_tokens": tokens,
        "owned_directory_domains": [
            d.strip() for d in settings.OWNED_DIRECTORY_DOMAINS.split(",") if d.strip()
        ],
    }


def _build_request(record: BacklinkRecord, project: Project | None, allow_render: bool) -> CrawlRequest:  # noqa: E501
    return CrawlRequest(
        source_url=record.source_page_url,
        target_url=record.target_url,
        expected_target_url=record.expected_target_url,
        expected_anchor_text=record.expected_anchor_text,
        expected_rel=record.expected_rel.value,
        backlink_id=str(record.id),
        treat_sponsored_as_follow=(
            project.treat_sponsored_as_follow if project else settings.QA_TREAT_SPONSORED_AS_FOLLOW
        ),
        trailing_slash_policy=settings.QA_TRAILING_SLASH_POLICY,
        respect_robots=settings.CRAWL_RESPECT_ROBOTS,
        allow_render=allow_render,
        **_relaxed_fields(record, project),
    )


async def _crawl_batch_async(ids: list[str], job_id: str | None, *, with_browser: bool) -> dict:
    uuids = [uuid.UUID(i) for i in ids]

    # 1) Load records + their projects in a short read-only session.
    async with session_scope() as s:
        records = list(
            (await s.execute(select(BacklinkRecord).where(BacklinkRecord.id.in_(uuids)))).scalars().all()
        )
        project_ids = {r.project_id for r in records}
        projects = {
            p.id: p
            for p in (await s.execute(select(Project).where(Project.id.in_(project_ids)))).scalars().all()  # noqa: E501
        }

    if not records:
        return {"processed": 0}

    # 2) Crawl concurrently — no DB session held during network I/O.
    browser = get_browser() if with_browser else None
    config = CrawlConfig.from_settings()
    limiter = make_rate_limiter(settings.CRAWL_DEFAULT_RATE_PER_SEC, settings.CRAWL_DEFAULT_BURST)
    engine = CrawlEngine(
        config, robots_cache=RedisRobotsCache(), browser=browser, rate_limiter=limiter
    )
    # allow_render is ALWAYS on: in the render pool the engine renders inline;
    # in the http pool it only sets render_recommended, which step 5 hands off
    # to the render queue. (It was tied to with_browser before, so the http pool
    # never recommended rendering — JS-only pages false-failed.)
    requests = [_build_request(r, projects.get(r.project_id), allow_render=True) for r in records]  # noqa: E501

    async with engine:
        artifacts = await asyncio.gather(
            *(engine.crawl(req) for req in requests), return_exceptions=True
        )

    # 3) Snapshot HTML to object storage (best-effort, off the DB).
    for record, artifact in zip(records, artifacts):
        if isinstance(artifact, BaseException):
            continue
        await _snapshot(record.id, artifact)

    # 4) Persist sequentially; each record its own transaction.
    succeeded = failed = 0
    render_ids: list[uuid.UUID] = []
    external_notifications: list[uuid.UUID] = []

    for record, artifact in zip(records, artifacts):
        if isinstance(artifact, BaseException):
            failed += 1
            log.warning("crawl_failed", backlink_id=str(record.id), error=repr(artifact))
            CRAWL_TOTAL.labels(mode="raw", outcome="error").inc()
            continue
        try:
            escalate = artifact.render_recommended and not with_browser and settings.RENDER_ENABLED  # noqa: E501
            fire_alerts = not escalate
            notif_ids = await _persist_one(record.id, artifact, job_id, fire_alerts)
            external_notifications.extend(notif_ids)
            CRAWL_TOTAL.labels(
                mode="rendered" if artifact.rendered else "raw", outcome="ok"
            ).inc()
            if escalate:
                # Hand off to the render pool: this record is NOT final in the HTTP
                # pass, so it is counted (processed + succeeded) by the render pass
                # ONLY — counting it here double-counts job/batch progress (the
                # over-count bug, batch #B-4: done 4306 > total 3777).
                render_ids.append(record.id)
                continue
            succeeded += 1
        except Exception as exc:  # noqa: BLE001 - isolate one bad record
            failed += 1
            log.error("persist_failed", backlink_id=str(record.id), error=repr(exc))

    # 5) Escalate to the render pool + dispatch external notifications.
    if render_ids:
        from app.workers.dispatch import enqueue_render

        for rid in render_ids:
            enqueue_render(rid, job_id=uuid.UUID(job_id) if job_id else None)

    if external_notifications:
        from app.workers.tasks.alerts import dispatch_notification

        for nid in external_notifications:
            dispatch_notification.apply_async(args=[str(nid)], queue="alerts")

    # 6) Job counters. Escalated records are counted by the render pass, not here,
    #    so each record increments job.processed exactly once (HTTP pass for
    #    non-escalated, render pass for escalated) — no over-count.
    if job_id:
        processed = len(records) - len(render_ids)
        await _update_job(uuid.UUID(job_id), processed, succeeded, failed)

    return {"processed": len(records), "succeeded": succeeded, "failed": failed}


async def _snapshot(backlink_id: uuid.UUID, artifact) -> None:
    try:
        if artifact.raw_html:
            key = storage.snapshot_key(str(backlink_id), "raw")
            await storage.put_bytes_async(
                settings.S3_BUCKET_SNAPSHOTS, key, artifact.raw_html.encode("utf-8"), "text/html"
            )
            artifact.raw_html_key = key
        if artifact.rendered_html:
            key = storage.snapshot_key(str(backlink_id), "rendered")
            await storage.put_bytes_async(
                settings.S3_BUCKET_SNAPSHOTS, key, artifact.rendered_html.encode("utf-8"), "text/html"  # noqa: E501
            )
            artifact.rendered_html_key = key
    except Exception as exc:  # noqa: BLE001 - storage outage must not fail the crawl
        log.warning("snapshot_failed", backlink_id=str(backlink_id), error=repr(exc))
    finally:
        artifact.raw_html = artifact.rendered_html = None  # free memory


async def _persist_one(
    backlink_id: uuid.UUID, artifact, job_id: str | None, fire_alerts: bool
) -> list[uuid.UUID]:
    async with session_scope() as s:
        record = await s.get(BacklinkRecord, backlink_id)
        if record is None:
            return []
        project = await s.get(Project, record.project_id)
        policy = QAPolicy.from_settings(
            treat_sponsored_as_follow=project.treat_sponsored_as_follow if project else None
        )
        # Resolve the active scoring rule set (project→link_type→workspace→global)
        # and derive metric signals; both fall back to today's behaviour if unset.
        ruleset = await scoring_config_service.resolve(
            s, record.workspace_id, record.project_id, record.link_type_id
        )
        # Source-domain metrics (DA / Semrush AS / age) feed the band signals; one
        # keyed lookup per record on (workspace_id, domain_key). None → bands omit.
        source_dom: SourceDomain | None = None
        if record.source_domain:
            source_dom = (
                await s.execute(
                    select(SourceDomain).where(
                        SourceDomain.workspace_id == record.workspace_id,
                        SourceDomain.domain_key == record.source_domain,
                    )
                )
            ).scalar_one_or_none()
        qa = evaluate(
            artifact, policy, ruleset=ruleset,
            signals=_scoring_signals(record, source_dom),
        )
        QA_VERDICTS.labels(status=qa.status.value).inc()

        interval = _INTERVAL_HOURS.get(
            project.schedule_interval if project else ScheduleInterval.DAILY,
            settings.DEFAULT_RECHECK_INTERVAL_HOURS,
        )
        _result, events = await result_service.persist(
            s, record, artifact, qa,
            crawl_job_id=uuid.UUID(job_id) if job_id else None,
            raw_html_key=artifact.raw_html_key,
            rendered_html_key=artifact.rendered_html_key,
            recheck_interval_hours=interval,
            scoring_rule_version_id=ruleset.version_id,
        )
        # Enrich with source-site metrics (Similarweb/Moz) — no-op unless configured.
        from app.integrations import site_metrics

        origin = await site_metrics.enrich(record)
        if origin in ("cached", "fresh") and record.source_domain:
            try:  # history is best-effort — never fail a crawl over bookkeeping
                from app.core.config import settings as _settings
                from app.models.metric_history import MetricCheckHistory

                s.add(
                    MetricCheckHistory(
                        workspace_id=record.workspace_id, entity_kind="domain",
                        entity_key=record.source_domain[:600],
                        provider=_settings.SITE_METRICS_PROVIDER,
                        from_cache=(origin == "cached"), ok=True,
                    )
                )
            except Exception:  # noqa: BLE001
                pass

        # ── QA attempt audit + API usage counters (Enterprise §2/§3) ─────────
        # Best-effort: bookkeeping never fails a crawl.
        try:
            await _record_attempt(s, record, artifact, qa, job_id)
        except Exception:  # noqa: BLE001
            pass

        external: list[uuid.UUID] = []
        if fire_alerts:
            notifs: list = []
            if events:
                notifs += await alert_service.evaluate(s, record, events)
            # Zero-config broken-link lifecycle alerts run on every crawl.
            notifs += await alert_service.evaluate_builtin(s, record)
            external = [n.id for n in notifs]
        await s.flush()
        # ids resolved after flush
        return external


# HTTP statuses that mean "the SERVICE was unavailable", not "the page is bad".
_TRANSIENT_HTTP = {402, 407, 429, 503, 504}
_MANUAL_SOURCES = ("recheck", "ui", "manual", "priority")


async def _record_attempt(s, record, artifact, qa, job_id: str | None) -> None:
    """One qa_attempts row per execution try + per-API usage counters."""
    from sqlalchemy import func as _f
    from sqlalchemy import select as _select

    from app.models.enums import OverallStatus as _OS
    from app.models.qa_attempt import QAAttempt
    from app.services import api_usage_service

    # Usage counters: the proxy (and render pool) consumed a request on this crawl.
    dur = artifact.crawl_duration_ms
    err = artifact.fetch_error_detail or (artifact.fetch_error.value if artifact.fetch_error.value != "none" else None)  # noqa: E501
    if artifact.egress == "proxy":
        await api_usage_service.record(
            "iproyal", ok=artifact.fetch_error.value == "none", duration_ms=dur, error=err
        )
    if artifact.rendered:
        await api_usage_service.record("render", ok=True, duration_ms=None)

    # Failure classification for the audit row (only when the try didn't produce
    # a real verdict — UNKNOWN means classify() saw a transient/external error).
    failure_kind = failure_api = None
    status = "success"
    if qa.status is _OS.UNKNOWN:
        status = "failed"
        fe = artifact.fetch_error.value
        if artifact.http_status == 429:
            failure_kind = "rate_limit"
        elif artifact.http_status in (402, 407):
            failure_kind = "auth"
        elif fe == "timeout":
            failure_kind = "timeout"
        elif fe in ("connection", "dns"):
            failure_kind = "network"
        else:
            failure_kind = "outage"
        failure_api = "iproyal" if artifact.egress == "proxy" else "target_site"

    n = (
        await s.execute(
            _select(_f.count()).select_from(QAAttempt).where(QAAttempt.backlink_id == record.id)
        )
    ).scalar() or 0
    trigger = "auto"
    triggered_by = None
    if job_id:
        job = await s.get(CrawlJob, uuid.UUID(job_id))
        if job is not None:
            # A user-created job carries triggered_by (recheck endpoints set it);
            # the beat dispatcher's jobs don't — that's the auto/manual line.
            if job.triggered_by is not None:
                trigger = "manual"
                triggered_by = job.triggered_by
            elif any(m in str((job.params or {}).get("source") or "") for m in _MANUAL_SOURCES):
                trigger = "manual"
    apis = []
    if artifact.egress == "proxy":
        apis.append("iproyal")
    if artifact.rendered:
        apis.append("render")
    s.add(
        QAAttempt(
            workspace_id=record.workspace_id,
            backlink_id=record.id,
            attempt_number=int(n) + 1,
            trigger_source=trigger,
            triggered_by=triggered_by,
            queue="crawl.render" if artifact.rendered else "crawl.http",
            apis_used=apis,
            request_count=1 + (1 if artifact.rendered else 0),
            duration_ms=dur,
            status=status,
            verdict=qa.status.value,
            failure_kind=failure_kind,
            failure_api=failure_api,
            error=(err or "")[:500] or None,
        )
    )


async def _update_job(job_id: uuid.UUID, processed: int, succeeded: int, failed: int) -> None:
    batch_id = None
    batch_done = False
    batch_totals: dict = {}
    async with session_scope() as s:
        await s.execute(
            update(CrawlJob)
            .where(CrawlJob.id == job_id)
            .values(
                processed=CrawlJob.processed + processed,
                succeeded=CrawlJob.succeeded + succeeded,
                failed=CrawlJob.failed + failed,
                status=JobStatus.RUNNING,
            )
        )
        job = await s.get(CrawlJob, job_id)
        if job and job.processed >= job.total:
            from datetime import datetime, timezone

            job.status = JobStatus.PARTIAL if job.failed else JobStatus.COMPLETED
            job.finished_at = datetime.now(timezone.utc)
        if job:
            batch_id = job.batch_id
            batch_done = job.processed >= job.total
            # Never surface done>total in the UI. The de-dup fix above prevents
            # over-count going forward; this clamps any residual/historical drift.
            done = min(job.processed, job.total) if job.total else job.processed
            batch_totals = {
                "total": job.total, "done": done,
                "ok": min(job.succeeded, job.total) if job.total else job.succeeded,
                "failed": job.failed,
            }
    # Mirror progress onto the operations batch (fail-open; separate session).
    if batch_id is not None:
        from app.services import batch_service

        await batch_service.update(batch_id, totals=batch_totals)
        if batch_done:
            await batch_service.finish(batch_id)


@celery_app.task(
    name="tasks.crawl.crawl_batch", bind=True, acks_late=True, max_retries=3,
    autoretry_for=(OperationalError,), retry_backoff=True, retry_jitter=True,
)
def crawl_batch(self, backlink_ids: list[str], job_id: str | None = None) -> dict:
    return run_async(_crawl_batch_async(backlink_ids, job_id, with_browser=False))


@celery_app.task(
    name="tasks.crawl.render_batch", bind=True, acks_late=True, max_retries=2,
    autoretry_for=(OperationalError,), retry_backoff=True,
)
def render_batch(self, backlink_ids: list[str], job_id: str | None = None) -> dict:
    return run_async(_crawl_batch_async(backlink_ids, job_id, with_browser=True))
