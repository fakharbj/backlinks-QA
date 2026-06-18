"""Prometheus metrics (Arch §15). Imported by API and workers alike."""

from __future__ import annotations

from prometheus_client import Counter, Gauge, Histogram

CRAWL_TOTAL = Counter(
    "ls_crawl_total", "Crawls attempted", ["mode", "outcome"]
)
CRAWL_DURATION = Histogram(
    "ls_crawl_duration_seconds",
    "Crawl fetch duration",
    ["mode"],
    buckets=(0.1, 0.25, 0.5, 1, 2, 3, 5, 8, 12, 20, 35),
)
RENDER_ESCALATIONS = Counter(
    "ls_render_escalations_total", "Times a raw crawl escalated to a render"
)
DOMAIN_THROTTLED = Counter(
    "ls_domain_throttled_total", "Requests deferred by per-domain token bucket"
)
CIRCUIT_OPENED = Counter(
    "ls_circuit_breaker_opened_total", "Per-domain circuit breaker openings"
)
QA_VERDICTS = Counter("ls_qa_verdicts_total", "QA verdicts produced", ["status"])
QUEUE_DEPTH = Gauge("ls_queue_depth", "Celery queue backlog", ["queue"])
ALERTS_DISPATCHED = Counter(
    "ls_alerts_dispatched_total", "Alerts dispatched", ["channel", "outcome"]
)
TASK_DURATION = Histogram(
    "ls_task_duration_seconds", "Celery task duration", ["task"]
)
