"""Index-check history (Phase 4).

One ``IndexCheck`` row per Google ``site:`` check of a SOURCE URL. Indexation is a
property of the source *page*, independent of the target/project, so checks are
deduped by ``source_key`` (sha256 of workspace + normalized source URL) — many
backlinks sharing a source URL cost one check. The latest verdict is also
denormalised onto ``backlink_records`` (index_status/…); this table keeps the
audit trail + evidence and powers "changes over time".
"""

from __future__ import annotations

import uuid
from datetime import datetime

from sqlalchemy import Integer, String, Text, func
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.dialects.postgresql import UUID as PGUUID
from sqlalchemy.orm import Mapped, mapped_column
from sqlalchemy import DateTime, Index

from app.db.base import Base, UUIDPrimaryKeyMixin

# Verdict values (plain strings; dynamic).
INDEXED = "indexed"
NOT_INDEXED = "not_indexed"
UNCERTAIN = "uncertain"


class IndexCheck(UUIDPrimaryKeyMixin, Base):
    __tablename__ = "index_checks"
    __table_args__ = (
        Index("ix_index_checks_source", "source_key", "queried_at"),
        Index("ix_index_checks_workspace", "workspace_id", "queried_at"),
    )

    workspace_id: Mapped[uuid.UUID] = mapped_column(PGUUID(as_uuid=True), nullable=False)
    source_key: Mapped[str] = mapped_column(String(64), nullable=False)  # hash, dedupe key
    source_url_normalized: Mapped[str] = mapped_column(Text, nullable=False)
    source_page_url: Mapped[str] = mapped_column(String(2048), nullable=False)

    verdict: Mapped[str] = mapped_column(String(20), nullable=False)  # indexed|not_indexed|uncertain
    result_count: Mapped[int | None] = mapped_column(Integer)
    provider: Mapped[str] = mapped_column(String(40), default="google_via_proxy")
    evidence: Mapped[dict] = mapped_column(JSONB, default=dict)
    queried_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )
