"""Metric check history (Phase 9 — freshness/audit layer).

One row per metric lookup: which entity (a domain or an exact page URL), which
provider answered, and whether the value came from cache or a fresh API call.
Powers "Checked recently" stamps, cache-hit counters on batches, and the audit
question "when did we last pay for this number?".
"""

from __future__ import annotations

import uuid
from datetime import datetime

from sqlalchemy import Boolean, DateTime, Index, String, func
from sqlalchemy.dialects.postgresql import UUID as PGUUID
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base, UUIDPrimaryKeyMixin


class MetricCheckHistory(UUIDPrimaryKeyMixin, Base):
    __tablename__ = "metric_check_history"
    __table_args__ = (
        Index("ix_metric_history_entity", "entity_kind", "entity_key", "fetched_at"),
        Index("ix_metric_history_batch", "batch_id"),
    )

    workspace_id: Mapped[uuid.UUID | None] = mapped_column(PGUUID(as_uuid=True))
    entity_kind: Mapped[str] = mapped_column(String(10), nullable=False)  # domain | page
    entity_key: Mapped[str] = mapped_column(String(600), nullable=False)  # domain or URL
    provider: Mapped[str] = mapped_column(String(30), nullable=False)  # similarweb|moz|serper|rdap
    from_cache: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)
    ok: Mapped[bool] = mapped_column(Boolean, default=True, nullable=False)
    batch_id: Mapped[uuid.UUID | None] = mapped_column(PGUUID(as_uuid=True))
    fetched_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )
