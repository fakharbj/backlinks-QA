"""Index-check orchestration (Phase 4).

Checks are deduped by SOURCE URL: ``check_source`` runs a Google ``site:`` query
(via ``integrations.serp``), records an ``IndexCheck`` row, and denormalises the
verdict onto every backlink that shares that source URL. ``select_due_sources``
finds the unique source URLs that are unchecked or past the re-check window, so a
manual run or the weekly job only spends queries where needed.
"""

from __future__ import annotations

import hashlib
import uuid
from datetime import datetime, timedelta, timezone

from sqlalchemy import func, select, text
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import settings
from app.core.logging import get_logger
from app.integrations import serp
from app.models.backlink import BacklinkRecord
from app.models.index_check import IndexCheck

log = get_logger("services.index")


def source_key(workspace_id: uuid.UUID, source_url_normalized: str) -> str:
    return hashlib.sha256(f"{workspace_id}|{source_url_normalized}".encode("utf-8")).hexdigest()


def _now() -> datetime:
    return datetime.now(timezone.utc)


async def check_source(
    db: AsyncSession,
    workspace_id: uuid.UUID,
    source_url_normalized: str,
    source_page_url: str,
    *,
    force: bool = False,
) -> dict:
    """Check one source URL's indexation (dedup-aware) and fan the verdict to backlinks."""
    key = source_key(workspace_id, source_url_normalized)

    if not force:
        cutoff = _now() - timedelta(days=max(1, settings.INDEX_RECHECK_DAYS))
        recent = (
            await db.execute(
                select(IndexCheck.verdict)
                .where(IndexCheck.source_key == key, IndexCheck.queried_at >= cutoff)
                .order_by(IndexCheck.queried_at.desc())
                .limit(1)
            )
        ).scalar_one_or_none()
        if recent is not None:
            return {"verdict": recent, "cached": True}

    result = await serp.check_indexed(source_page_url)
    verdict = result["verdict"]
    count = result["result_count"]
    now = _now()

    db.add(
        IndexCheck(
            workspace_id=workspace_id, source_key=key,
            source_url_normalized=source_url_normalized, source_page_url=source_page_url,
            verdict=verdict, result_count=count, evidence=result["evidence"], queried_at=now,
        )
    )
    # Denormalise onto every backlink with this source URL (UNCERTAIN does not
    # overwrite a previous confident verdict — we keep the last known good status).
    if verdict == serp.UNCERTAIN:
        await db.execute(
            text(
                "UPDATE backlink_records SET index_checked_at=:now "
                "WHERE workspace_id=:ws AND source_url_normalized=:src"
            ),
            {"now": now, "ws": workspace_id, "src": source_url_normalized},
        )
    else:
        # Timeline events for links whose denormalised status actually FLIPS
        # (prior non-NULL verdict that differs). First-time verdicts (NULL → x)
        # are skipped — they fire for every link on the first weekly sweep.
        flips = (
            await db.execute(
                select(
                    BacklinkRecord.id,
                    BacklinkRecord.workspace_id,
                    BacklinkRecord.project_id,
                    BacklinkRecord.index_status,
                ).where(
                    BacklinkRecord.workspace_id == workspace_id,
                    BacklinkRecord.source_url_normalized == source_url_normalized,
                    BacklinkRecord.index_status.is_not(None),
                    BacklinkRecord.index_status != verdict,
                )
            )
        ).all()
        await db.execute(
            text(
                "UPDATE backlink_records SET index_status=:v, index_result_count=:c, "
                "index_checked_at=:now WHERE workspace_id=:ws AND source_url_normalized=:src"
            ),
            {"v": verdict, "c": count, "now": now, "ws": workspace_id, "src": source_url_normalized},
        )
        if flips:
            from app.models.enums import HistoryEventType
            from app.services import history_service

            for flip in flips:
                await history_service.record_event_for_ids(
                    db, backlink_id=flip.id, workspace_id=flip.workspace_id,
                    project_id=flip.project_id,
                    event_type=HistoryEventType.INDEX_STATUS_CHANGED,
                    field="index_status", old_value=flip.index_status,
                    new_value=verdict, source="worker",
                )
    await db.flush()
    return {"verdict": verdict, "result_count": count, "cached": False}


async def select_due_sources(
    db: AsyncSession,
    *,
    workspace_id: uuid.UUID | None = None,
    project_id: uuid.UUID | None = None,
    force: bool = False,
    limit: int | None = None,
) -> list[tuple[uuid.UUID, str, str]]:
    """Unique (workspace_id, source_url_normalized, source_page_url) due for a check."""
    limit = limit or settings.INDEX_BATCH_LIMIT
    cutoff = _now() - timedelta(days=max(1, settings.INDEX_RECHECK_DAYS))

    where = []
    params: dict = {"cutoff": cutoff, "lim": limit}
    if workspace_id is not None:
        where.append("workspace_id = :ws")
        params["ws"] = workspace_id
    if project_id is not None:
        where.append("project_id = :pid")
        params["pid"] = project_id
    where_sql = (" WHERE " + " AND ".join(where)) if where else ""
    having_sql = "" if force else "HAVING max(index_checked_at) IS NULL OR max(index_checked_at) < :cutoff"

    sql = text(
        f"""
        SELECT workspace_id, source_url_normalized, min(source_page_url) AS url
        FROM backlink_records{where_sql}
        GROUP BY workspace_id, source_url_normalized
        {having_sql}
        ORDER BY max(index_checked_at) NULLS FIRST
        LIMIT :lim
        """
    )
    rows = (await db.execute(sql, params)).all()
    return [(r.workspace_id, r.source_url_normalized, r.url) for r in rows]


async def summary(db: AsyncSession, workspace_id: uuid.UUID, project_id: uuid.UUID | None) -> dict:
    """Counts by index_status for the report/dashboard."""
    where = "workspace_id = :ws"
    params: dict = {"ws": workspace_id}
    if project_id is not None:
        where += " AND project_id = :pid"
        params["pid"] = project_id
    rows = (
        await db.execute(
            text(
                f"SELECT coalesce(index_status, 'unchecked') AS s, count(*) AS n "
                f"FROM backlink_records WHERE {where} GROUP BY 1"
            ),
            params,
        )
    ).all()
    return {r.s: r.n for r in rows}
