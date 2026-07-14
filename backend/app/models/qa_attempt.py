"""QA execution attempts (Enterprise refinement §2).

One row per QA execution TRY — success, failure, or blocked-before-run — so the
"why is this link still pending?" question always has an answer: which attempt,
when, triggered by whom, which APIs it used, how long it took, and exactly what
failed. Complements crawl_results (which only exists when a crawl produced a
verdict); qa_attempts also records tries that died on an API failure.
"""

from __future__ import annotations

import uuid
from datetime import datetime

from sqlalchemy import DateTime, ForeignKey, Index, Integer, String, func
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.dialects.postgresql import UUID as PGUUID
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base, UUIDPrimaryKeyMixin

# qa_wait_reason vocabulary on backlink_records (why QA is NOT running):
WAIT_API_FAILED = "api_failed"      # last try died on a recoverable API failure
WAIT_FOR_QUOTA = "waiting_api"      # quota exhausted before dispatch
WAIT_MANUAL = "manual_retry"        # a human paused it / wants manual control


class QAAttempt(UUIDPrimaryKeyMixin, Base):
    __tablename__ = "qa_attempts"
    __table_args__ = (
        Index("ix_qa_attempts_backlink", "backlink_id", "created_at"),
        Index("ix_qa_attempts_ws", "workspace_id", "created_at"),
    )

    workspace_id: Mapped[uuid.UUID] = mapped_column(
        PGUUID(as_uuid=True), ForeignKey("workspaces.id", ondelete="CASCADE"), nullable=False
    )
    backlink_id: Mapped[uuid.UUID] = mapped_column(PGUUID(as_uuid=True), nullable=False)
    attempt_number: Mapped[int] = mapped_column(Integer, default=1, nullable=False)
    trigger_source: Mapped[str] = mapped_column(String(12), default="auto", nullable=False)  # auto|manual
    triggered_by: Mapped[uuid.UUID | None] = mapped_column(PGUUID(as_uuid=True))
    queue: Mapped[str | None] = mapped_column(String(30))
    apis_used: Mapped[list] = mapped_column(JSONB, default=list, nullable=False)
    request_count: Mapped[int] = mapped_column(Integer, default=1, nullable=False)
    duration_ms: Mapped[int | None] = mapped_column(Integer)
    status: Mapped[str] = mapped_column(String(12), nullable=False)  # success|failed|blocked
    verdict: Mapped[str | None] = mapped_column(String(30))
    failure_kind: Mapped[str | None] = mapped_column(String(30))     # timeout|rate_limit|auth|outage|network|quota
    failure_api: Mapped[str | None] = mapped_column(String(30))
    error: Mapped[str | None] = mapped_column(String(500))
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )
