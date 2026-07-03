"""Generated reports (PRD §8.16)."""

from __future__ import annotations

import uuid
from datetime import datetime

from sqlalchemy import Boolean, DateTime, ForeignKey, Index, Integer, String, Text
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.dialects.postgresql import UUID as PGUUID
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base, TimestampMixin, UUIDPrimaryKeyMixin
from app.db.types import pg_enum
from app.models.enums import ReportFormat, ReportStatus, ReportType


class Report(UUIDPrimaryKeyMixin, TimestampMixin, Base):
    __tablename__ = "reports"
    __table_args__ = (
        Index("ix_reports_workspace_created", "workspace_id", "created_at"),
        Index("ix_reports_project", "project_id"),
    )

    workspace_id: Mapped[uuid.UUID] = mapped_column(
        PGUUID(as_uuid=True), ForeignKey("workspaces.id", ondelete="CASCADE"), nullable=False
    )
    project_id: Mapped[uuid.UUID | None] = mapped_column(
        PGUUID(as_uuid=True), ForeignKey("projects.id", ondelete="SET NULL")
    )
    created_by: Mapped[uuid.UUID | None] = mapped_column(
        PGUUID(as_uuid=True), ForeignKey("users.id", ondelete="SET NULL")
    )
    report_type: Mapped[ReportType] = mapped_column(
        pg_enum(ReportType, "report_type_enum"), nullable=False
    )
    format: Mapped[ReportFormat] = mapped_column(
        pg_enum(ReportFormat, "report_format_enum"), nullable=False
    )
    status: Mapped[ReportStatus] = mapped_column(
        pg_enum(ReportStatus, "report_status_enum"),
        default=ReportStatus.PENDING,
        nullable=False,
    )
    title: Mapped[str] = mapped_column(String(300), nullable=False)
    filters: Mapped[dict] = mapped_column(JSONB, default=dict)  # frozen filter snapshot
    # Operations-layer batch this run belongs to (Phase 9; nullable pre-9 rows).
    batch_id: Mapped[uuid.UUID | None] = mapped_column(PGUUID(as_uuid=True))
    file_key: Mapped[str | None] = mapped_column(String(500))
    file_size: Mapped[int | None] = mapped_column(Integer)
    row_count: Mapped[int | None] = mapped_column(Integer)
    error: Mapped[str | None] = mapped_column(Text)
    completed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))

    # ── Versioning (Phase 6) — each generation is a frozen snapshot ───────────
    version: Mapped[int] = mapped_column(Integer, default=1, nullable=False)
    is_latest: Mapped[bool] = mapped_column(Boolean, default=True, nullable=False)
    output_target: Mapped[str] = mapped_column(String(20), default="download")  # download|google_sheet
