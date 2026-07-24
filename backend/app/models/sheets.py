"""Google Sheets connection state (Phase 2).

One ``SheetSource`` per connected project sheet — a row in the global main sheet
maps Project Name → Project Sheet URL, and each such project sheet becomes one
``SheetSource`` (1:1 with a project). Sync state and the per-sheet column mapping
and write-back allow-list live here so syncing is dynamic and auditable.
"""

from __future__ import annotations

import uuid
from datetime import datetime

from sqlalchemy import DateTime, ForeignKey, Index, Integer, String, UniqueConstraint
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.dialects.postgresql import UUID as PGUUID
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base, TimestampMixin, UUIDPrimaryKeyMixin


class SheetSource(UUIDPrimaryKeyMixin, TimestampMixin, Base):
    __tablename__ = "sheet_sources"
    __table_args__ = (
        UniqueConstraint("project_id", name="uq_sheet_sources_project"),
        UniqueConstraint(
            "workspace_id", "spreadsheet_id", "sheet_tab",
            name="uq_sheet_sources_ws_spreadsheet_tab",
        ),
        Index("ix_sheet_sources_workspace", "workspace_id"),
    )

    workspace_id: Mapped[uuid.UUID] = mapped_column(
        PGUUID(as_uuid=True), ForeignKey("workspaces.id", ondelete="CASCADE"), nullable=False
    )
    project_id: Mapped[uuid.UUID] = mapped_column(
        PGUUID(as_uuid=True), ForeignKey("projects.id", ondelete="CASCADE"), nullable=False
    )

    project_name: Mapped[str] = mapped_column(String(300), nullable=False)  # as seen in main sheet
    spreadsheet_id: Mapped[str] = mapped_column(String(120), nullable=False)
    sheet_tab: Mapped[str | None] = mapped_column(String(200))  # None → first worksheet
    source_url: Mapped[str | None] = mapped_column(String(1000))  # original link from main sheet

    # header → canonical field (overrides the auto-mapping when present).
    column_mapping: Mapped[dict] = mapped_column(JSONB, default=dict)

    # Sync state.
    last_synced_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    last_sync_status: Mapped[str | None] = mapped_column(String(40))  # ok | error | running
    last_sync_error: Mapped[str | None] = mapped_column(String(1000))
    last_sync_import_id: Mapped[uuid.UUID | None] = mapped_column(PGUUID(as_uuid=True))
    row_count: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    imported_count: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    updated_count: Mapped[int] = mapped_column(Integer, default=0, nullable=False)

    # Write-back (Phase 6) — RESULT columns only; never overwrite input columns.
    writeback_enabled: Mapped[bool] = mapped_column(default=False, nullable=False)
    writeback_columns: Mapped[dict] = mapped_column(JSONB, default=dict)

    # Pending Project-Sheet-URL change (owner rule): when the main sheet points a
    # project at a DIFFERENT spreadsheet, we do NOT silently repoint + resync (that
    # could pull a wrong sheet's data). The new target is parked here and the
    # active spreadsheet_id keeps serving until an admin confirms it — at which
    # point the new sheet is validated (readable) and applied. Cleared on confirm
    # or dismiss.
    pending_spreadsheet_id: Mapped[str | None] = mapped_column(String(120))
    pending_source_url: Mapped[str | None] = mapped_column(String(1000))
    url_change_detected_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
