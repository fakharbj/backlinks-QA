"""Celery application + queue topology + beat schedule (Arch §5/§6).

Queues are split so a flood of one workload never starves another:
  * ``crawl.http.<n>`` — domain-sharded light HTTP crawling (the bulk).
  * ``crawl.render``   — Playwright renders (CPU/RAM heavy, isolated).
  * ``qa`` / ``alerts``— standalone QA re-eval + notification dispatch.
  * ``reports``        — CSV/XLSX/PDF generation.
  * ``maintenance``    — matview refresh, partition roll, retention, due dispatch.
"""

from __future__ import annotations

from celery import Celery
from celery.schedules import crontab
from kombu import Queue

from app.core.config import settings

celery_app = Celery("linksentinel")

celery_app.conf.update(
    broker_url=str(settings.CELERY_BROKER_URL),
    result_backend=str(settings.CELERY_RESULT_BACKEND),
    task_serializer="json",
    result_serializer="json",
    accept_content=["json"],
    timezone="UTC",
    enable_utc=True,
    # Long crawl tasks: fair dispatch + at-least-once with idempotent writes.
    task_acks_late=True,
    task_reject_on_worker_lost=True,
    worker_prefetch_multiplier=1,
    worker_max_tasks_per_child=200,        # recycle to bound memory (esp. render)
    task_track_started=True,
    task_time_limit=600,                   # hard ceiling
    task_soft_time_limit=540,
    broker_transport_options={"visibility_timeout": 3600, "queue_order_strategy": "priority"},
    result_expires=3600,
    task_default_queue="default",
)

# Queue set (HTTP shards are generated from CRAWL_QUEUE_SHARDS).
_http_shards = [Queue(f"crawl.http.{i}") for i in range(settings.CRAWL_QUEUE_SHARDS)]
celery_app.conf.task_queues = [
    Queue("default"),
    *_http_shards,
    Queue("crawl.render"),
    Queue("qa"),
    Queue("alerts"),
    Queue("reports"),
    Queue("maintenance"),
]

celery_app.conf.task_routes = {
    "tasks.crawl.render_batch": {"queue": "crawl.render"},
    "tasks.imports.process_import": {"queue": "default"},
    "tasks.reports.generate_report": {"queue": "reports"},
    "tasks.alerts.dispatch_notification": {"queue": "alerts"},
    "tasks.maintenance.*": {"queue": "maintenance"},
    # crawl_batch is routed explicitly per-shard at dispatch time.
}

# Beat schedule (RedBeat lock keeps a single scheduler in HA).
celery_app.conf.redbeat_redis_url = str(settings.CELERY_BROKER_URL)
celery_app.conf.beat_schedule = {
    "dispatch-due-rechecks": {
        "task": "tasks.maintenance.dispatch_due_rechecks",
        "schedule": 300.0,  # every 5 minutes
    },
    # NOTE: the dashboard reads backlink_records live (app/services/dashboard_service.py),
    # so there is no materialized view to refresh anymore — that job was removed.
    "ensure-partitions": {
        "task": "tasks.maintenance.ensure_partitions",
        "schedule": crontab(hour="3", minute="0"),
    },
    "retention-cleanup": {
        "task": "tasks.maintenance.retention_cleanup",
        "schedule": crontab(hour="4", minute="0"),
    },
}

# Register tasks by importing the modules (their decorators bind to celery_app).
celery_app.autodiscover_tasks(
    [
        "app.workers.tasks.crawl",
        "app.workers.tasks.imports",
        "app.workers.tasks.reports",
        "app.workers.tasks.alerts",
        "app.workers.tasks.maintenance",
    ],
    force=True,
)
