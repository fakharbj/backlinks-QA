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
from app.qa import evaluate
from app.qa.types import QAPolicy
from app.services import alert_service, result_service, scoring_config_service
from app.workers.celery_app import celery_app
from app.workers.runtime import RedisRobotsCache, get_browser, make_rate_limiter, run_async

log = get_logger("worker.crawl")


def _scoring_signals(record: BacklinkRecord) -> dict[str, str]:
    """Metric-parameter values for the scorer (duplicate / external index). DA /
    Semrush / age bands are looked up only when a rule set configures them; they
    default to no contribution otherwise (added in a later increment)."""
    signals: dict[str, str] = {}
    dup = record.duplicate_status
    if dup:
        signals["duplicate"] = "unique" if dup == "unique" else "duplicate"
    idx = record.index_status
    if idx in ("indexed", "not_indexed"):
        signals["external_index"] = idx
    return signals

_INTERVAL_HOURS = {
    ScheduleInterval.DAILY: 24,
    ScheduleInterval.WEEKLY: 24 * 7,
    ScheduleInterval.MONTHLY: 24 * 30,
    ScheduleInterval.MANUAL: settings.DEFAULT_RECHECK_INTERVAL_HOURS,
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
            fire_alerts = not (artifact.render_recommended and not with_browser and settings.RENDER_ENABLED)  # noqa: E501
            notif_ids = await _persist_one(record.id, artifact, job_id, fire_alerts)
            external_notifications.extend(notif_ids)
            if artifact.render_recommended and not with_browser and settings.RENDER_ENABLED:
                render_ids.append(record.id)
            succeeded += 1
            CRAWL_TOTAL.labels(
                mode="rendered" if artifact.rendered else "raw", outcome="ok"
            ).inc()
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

    # 6) Job counters.
    if job_id:
        await _update_job(uuid.UUID(job_id), len(records), succeeded, failed)

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
        qa = evaluate(artifact, policy, ruleset=ruleset, signals=_scoring_signals(record))
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
            batch_totals = {
                "total": job.total, "done": job.processed,
                "ok": job.succeeded, "failed": job.failed,
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
