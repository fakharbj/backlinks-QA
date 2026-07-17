"""Temp QA lab models (Phase 11) — candidate backlink tests, fully isolated.

Deliberately NOT related to BacklinkRecord / Project / SourceDomain: a QA test
is a throwaway space for checking a candidate's links. Results live only here.
"""

from __future__ import annotations

import uuid
from datetime import datetime

from sqlalchemy import Boolean, DateTime, ForeignKey, Integer, String, Text
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.dialects.postgresql import UUID as PGUUID
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base, TimestampMixin, UUIDPrimaryKeyMixin


class QATestBatch(UUIDPrimaryKeyMixin, TimestampMixin, Base):
    __tablename__ = "qa_test_batches"

    workspace_id: Mapped[uuid.UUID] = mapped_column(
        PGUUID(as_uuid=True), ForeignKey("workspaces.id", ondelete="CASCADE"), nullable=False
    )
    candidate_name: Mapped[str] = mapped_column(String(200), nullable=False)
    candidate_email: Mapped[str | None] = mapped_column(String(255))
    role_applied: Mapped[str | None] = mapped_column(String(120))
    notes: Mapped[str | None] = mapped_column(String(1000))
    status: Mapped[str] = mapped_column(String(12), default="draft", nullable=False)
    created_by: Mapped[uuid.UUID | None] = mapped_column(PGUUID(as_uuid=True))


class QATestLink(UUIDPrimaryKeyMixin, Base):
    __tablename__ = "qa_test_links"

    batch_id: Mapped[uuid.UUID] = mapped_column(
        PGUUID(as_uuid=True), ForeignKey("qa_test_batches.id", ondelete="CASCADE"), nullable=False
    )
    workspace_id: Mapped[uuid.UUID] = mapped_column(
        PGUUID(as_uuid=True), ForeignKey("workspaces.id", ondelete="CASCADE"), nullable=False
    )
    source_url: Mapped[str] = mapped_column(Text, nullable=False)
    target_url: Mapped[str | None] = mapped_column(Text)
    anchor_text: Mapped[str | None] = mapped_column(String(500))
    link_type: Mapped[str | None] = mapped_column(String(80))
    expected_rel: Mapped[str | None] = mapped_column(String(20))
    # pending → checking → checked | failed
    state: Mapped[str] = mapped_column(String(12), default="pending", nullable=False)
    status: Mapped[str | None] = mapped_column(String(24))
    score: Mapped[int | None] = mapped_column(Integer)
    link_found: Mapped[bool | None] = mapped_column(Boolean)
    http_status: Mapped[int | None] = mapped_column(Integer)
    current_rel: Mapped[str | None] = mapped_column(String(20))
    current_anchor: Mapped[str | None] = mapped_column(String(500))
    indexability: Mapped[str | None] = mapped_column(String(20))
    matched_href: Mapped[str | None] = mapped_column(Text)
    top_issue: Mapped[str | None] = mapped_column(String(80))
    facts: Mapped[dict] = mapped_column(JSONB, default=dict)
    error: Mapped[str | None] = mapped_column(String(500))
    checked_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
