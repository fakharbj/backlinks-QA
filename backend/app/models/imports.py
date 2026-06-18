"""Resumable import staging (PRD §8.3)."""

from __future__ import annotations

import uuid

from sqlalchemy import ForeignKey, Index, Integer, String, Text
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.dialects.postgresql import UUID as PGUUID
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base, TimestampMixin, UUIDPrimaryKeyMixin
from app.db.types import pg_enum
from app.models.enums import ImportRowStatus, ImportSource, ImportStatus


class Import(UUIDPrimaryKeyMixin, TimestampMixin, Base):
    __tablename__ = "imports"
    __table_args__ = (Index("ix_imports_project", "project_id"),)

    workspace_id: Mapped[uuid.UUID] = mapped_column(
        PGUUID(as_uuid=True), ForeignKey("workspaces.id", ondelete="CASCADE"), nullable=False
    )
    project_id: Mapped[uuid.UUID] = mapped_column(
        PGUUID(as_uuid=True), ForeignKey("projects.id", ondelete="CASCADE"), nullable=False
    )
    created_by: Mapped[uuid.UUID | None] = mapped_column(
        PGUUID(as_uuid=True), ForeignKey("users.id", ondelete="SET NULL")
    )
    source: Mapped[ImportSource] = mapped_column(
        pg_enum(ImportSource, "import_source_enum"), nullable=False
    )
    filename: Mapped[str | None] = mapped_column(String(500))
    upload_key: Mapped[str | None] = mapped_column(String(500))  # object-storage key
    column_mapping: Mapped[dict] = mapped_column(JSONB, default=dict)
    status: Mapped[ImportStatus] = mapped_column(
        pg_enum(ImportStatus, "import_status_enum"),
        default=ImportStatus.PENDING,
        nullable=False,
    )
    total_rows: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    processed_rows: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    imported_rows: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    duplicate_rows: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    error_rows: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    error: Mapped[str | None] = mapped_column(Text)


class ImportRow(UUIDPrimaryKeyMixin, Base):
    """One staged row; survives crashes so large imports resume (PRD §8.3)."""

    __tablename__ = "import_rows"
    __table_args__ = (
        Index("ix_import_rows_import_status", "import_id", "status"),
        Index("ix_import_rows_import_line", "import_id", "row_number"),
    )

    import_id: Mapped[uuid.UUID] = mapped_column(
        PGUUID(as_uuid=True), ForeignKey("imports.id", ondelete="CASCADE"), nullable=False
    )
    row_number: Mapped[int] = mapped_column(Integer, nullable=False)
    raw: Mapped[dict] = mapped_column(JSONB, default=dict)            # original row
    mapped: Mapped[dict] = mapped_column(JSONB, default=dict)         # canonical fields
    status: Mapped[ImportRowStatus] = mapped_column(
        pg_enum(ImportRowStatus, "import_row_status_enum"),
        default=ImportRowStatus.PENDING,
        nullable=False,
    )
    error: Mapped[str | None] = mapped_column(Text)
    backlink_id: Mapped[uuid.UUID | None] = mapped_column(PGUUID(as_uuid=True))
