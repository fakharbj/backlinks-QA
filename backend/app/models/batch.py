"""Unified batch registry (Phase 9 — every run is a batch).

One row per run of anything long-running — sheet syncs, imports, write-backs,
crawls/rechecks, index sweeps, duplicate scans, re-scores, competitor runs,
reports. Existing runner tables (``imports``, ``crawl_jobs``, ``reports``) stay
the source of row-level truth; the batch row is the operations layer on top:
status, progress, counters, and human-readable logs, so users get one history
across the whole product ("what ran, when, by whom, what happened").

Writes to these tables are ALWAYS fail-open (see ``services.batch_service``):
a logging problem must never fail the underlying sync/import/crawl.
"""

from __future__ import annotations

import uuid
from datetime import datetime

from sqlalchemy import DateTime, Index, String, Text, func, text
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.dialects.postgresql import UUID as PGUUID
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base, TimestampMixin, UUIDPrimaryKeyMixin

# Batch kinds (plain strings — adding a kind must never need a migration).
BATCH_KINDS = (
    "import", "sheet_sync", "writeback", "crawl", "recheck", "index_check",
    "duplicate_scan", "rescore", "competitor_import", "report",
)


class Batch(UUIDPrimaryKeyMixin, TimestampMixin, Base):
    __tablename__ = "batches"
    __table_args__ = (
        Index("ix_batches_workspace_created", "workspace_id", "created_at"),
        Index("ix_batches_kind_status", "workspace_id", "kind", "status"),
        Index("ix_batches_project", "project_id"),
    )

    workspace_id: Mapped[uuid.UUID] = mapped_column(PGUUID(as_uuid=True), nullable=False)
    project_id: Mapped[uuid.UUID | None] = mapped_column(PGUUID(as_uuid=True))
    kind: Mapped[str] = mapped_column(String(30), nullable=False)
    # pending | running | completed | failed | partial
    status: Mapped[str] = mapped_column(String(20), default="running", nullable=False)
    label: Mapped[str | None] = mapped_column(String(300))  # human name (sheet, file…)
    started_by: Mapped[uuid.UUID | None] = mapped_column(PGUUID(as_uuid=True))
    # {"total": n, "done": n, "ok": n, "failed": n, "skipped": n}
    totals: Mapped[dict] = mapped_column(JSONB, nullable=False, server_default=text("'{}'::jsonb"))
    # {"api_calls": n, "api_cached": n, "dup_new": n, "dup_previous": n, ...}
    counters: Mapped[dict] = mapped_column(JSONB, nullable=False, server_default=text("'{}'::jsonb"))
    meta: Mapped[dict] = mapped_column(JSONB, nullable=False, server_default=text("'{}'::jsonb"))
    error: Mapped[str | None] = mapped_column(Text)
    started_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )
    finished_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))


class BatchLog(UUIDPrimaryKeyMixin, Base):
    __tablename__ = "batch_logs"
    __table_args__ = (Index("ix_batch_logs_batch_created", "batch_id", "created_at"),)

    batch_id: Mapped[uuid.UUID] = mapped_column(PGUUID(as_uuid=True), nullable=False)
    level: Mapped[str] = mapped_column(String(10), default="info", nullable=False)  # info|warn|error
    message: Mapped[str] = mapped_column(Text, nullable=False)
    row_ref: Mapped[str | None] = mapped_column(String(120))  # tab/row or entity hint
    data: Mapped[dict] = mapped_column(JSONB, nullable=False, server_default=text("'{}'::jsonb"))
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )
