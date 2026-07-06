"""Google Sheet sub-sheets / tabs (Phase 8, features 5/6).

Each project spreadsheet has one or more tabs; a tab name IS the link type
(Web 2.0, Profile, Business Listing, …). One ``GoogleSheetTab`` per detected tab,
keyed by the stable ``gid`` (survives renames). ``import_enabled`` / ``qa_enabled``
are the per-tab checkboxes; ``link_type_name`` defaults to the tab name.
"""

from __future__ import annotations

import uuid
from datetime import datetime

from sqlalchemy import Boolean, DateTime, ForeignKey, Index, Integer, String, UniqueConstraint
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.dialects.postgresql import UUID as PGUUID
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base, TimestampMixin, UUIDPrimaryKeyMixin


class GoogleSheetTab(UUIDPrimaryKeyMixin, TimestampMixin, Base):
    __tablename__ = "google_sheet_project_tabs"
    __table_args__ = (
        UniqueConstraint("sheet_source_id", "gid", name="uq_sheet_tabs_source_gid"),
        Index("ix_sheet_tabs_source", "sheet_source_id"),
    )

    workspace_id: Mapped[uuid.UUID] = mapped_column(
        PGUUID(as_uuid=True), ForeignKey("workspaces.id", ondelete="CASCADE"), nullable=False
    )
    sheet_source_id: Mapped[uuid.UUID] = mapped_column(
        PGUUID(as_uuid=True), ForeignKey("sheet_sources.id", ondelete="CASCADE"), nullable=False
    )
    gid: Mapped[str] = mapped_column(String(40), nullable=False)  # stable tab id
    tab_name: Mapped[str] = mapped_column(String(200), nullable=False)
    link_type_name: Mapped[str | None] = mapped_column(String(80))  # defaults to tab_name
    import_enabled: Mapped[bool] = mapped_column(Boolean, default=True, nullable=False)
    qa_enabled: Mapped[bool] = mapped_column(Boolean, default=True, nullable=False)
    status: Mapped[str] = mapped_column(String(20), default="detected", nullable=False)  # detected|missing
    row_count: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    last_synced_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    # Per-tab header→canonical-field override; null = inherit source default then auto-map.
    column_mapping: Mapped[dict | None] = mapped_column(JSONB)
    # canonical field → literal value applied to every row on the tab (e.g. link_type).
    field_constants: Mapped[dict | None] = mapped_column(JSONB)
    # 1-based row where headers live; null = 1.
    header_row: Mapped[int | None] = mapped_column(Integer)
    # last-seen headers, for the mapping UI + drift detection.
    headers_snapshot: Mapped[list | None] = mapped_column(JSONB)
