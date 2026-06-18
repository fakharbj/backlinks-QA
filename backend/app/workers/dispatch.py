"""Task dispatch helpers (imported lazily by the API).

Chunks backlink ids into batches and routes them across the ``crawl.http.<n>``
shards. Per-domain politeness is enforced globally by the Redis token bucket
inside the engine, so id-hash sharding here is purely for load balancing.
"""

from __future__ import annotations

import uuid
from collections.abc import Iterable, Sequence

from app.core.config import settings


def _chunks(items: Sequence, size: int) -> Iterable[Sequence]:
    for i in range(0, len(items), size):
        yield items[i : i + size]


def enqueue_backlinks(
    ids: Sequence[uuid.UUID], *, job_id: uuid.UUID | None = None, priority: bool = False
) -> int:
    from app.workers.tasks.crawl import crawl_batch

    ids = [str(i) for i in ids]
    shards = max(1, settings.CRAWL_QUEUE_SHARDS)
    batch_size = settings.CRAWL_BATCH_SIZE_HTTP
    prio = 9 if priority else 5
    queued = 0
    for index, chunk in enumerate(_chunks(ids, batch_size)):
        queue = f"crawl.http.{index % shards}"
        crawl_batch.apply_async(
            args=[list(chunk), str(job_id) if job_id else None],
            queue=queue,
            priority=prio,
        )
        queued += len(chunk)
    return queued


def enqueue_render(backlink_id: uuid.UUID, *, job_id: uuid.UUID | None = None) -> None:
    from app.workers.tasks.crawl import render_batch

    render_batch.apply_async(
        args=[[str(backlink_id)], str(job_id) if job_id else None],
        queue="crawl.render",
        priority=6,
    )


def enqueue_import(import_id: uuid.UUID, *, parse_from_storage: bool) -> None:
    from app.workers.tasks.imports import process_import

    process_import.apply_async(args=[str(import_id), parse_from_storage], queue="default")


def enqueue_report(report_id: uuid.UUID) -> None:
    from app.workers.tasks.reports import generate_report

    generate_report.apply_async(args=[str(report_id)], queue="reports")
