"""Source main-domain aggregates (Phase 8, features 11/12/14).

One row per (workspace, source main domain). The counters are STORED and refreshed
by ``source_domain_service.recompute`` (set-based SQL), so dashboards read
index/non-index ratios etc. from these columns instead of scanning the backlink
table on every request. Domain-authority / Semrush metrics attach in a later
increment (separate tables keyed by domain).
"""

from __future__ import annotations

import uuid
from datetime import date, datetime

from sqlalchemy import (
    BigInteger,
    Date,
    DateTime,
    ForeignKey,
    Index,
    Integer,
    Numeric,
    String,
    UniqueConstraint,
)
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.dialects.postgresql import UUID as PGUUID
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base, TimestampMixin, UUIDPrimaryKeyMixin


class SourceDomain(UUIDPrimaryKeyMixin, TimestampMixin, Base):
    __tablename__ = "source_domains"
    __table_args__ = (
        UniqueConstraint("workspace_id", "domain_key", name="uq_source_domains_ws_domain"),
        Index("ix_source_domains_workspace", "workspace_id"),
        Index("ix_source_domains_backlinks", "workspace_id", "backlink_count"),
    )

    workspace_id: Mapped[uuid.UUID] = mapped_column(
        PGUUID(as_uuid=True), ForeignKey("workspaces.id", ondelete="CASCADE"), nullable=False
    )
    domain_key: Mapped[str] = mapped_column(String(255), nullable=False)  # registrable domain
    grouping: Mapped[str] = mapped_column(String(20), default="registrable", nullable=False)
    # 'derived' rows are rebuilt from backlinks (recompute deletes orphans);
    # 'imported' rows were approved from a domain-import batch and survive
    # recompute even with zero backlinks (0029).
    origin: Mapped[str] = mapped_column(String(12), default="derived", server_default="derived", nullable=False)

    backlink_count: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    indexed_count: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    not_indexed_count: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    uncertain_count: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    unchecked_count: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    dofollow_count: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    nofollow_count: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    duplicate_count: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    avg_score: Mapped[float | None] = mapped_column(Numeric(5, 1))
    link_type_distribution: Mapped[dict] = mapped_column(JSONB, default=dict)
    project_count: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    user_count: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    last_recomputed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))

    # ── Third-party metrics (Phase 8 F21/F22/F23) — per source main domain ────
    da: Mapped[int | None] = mapped_column(Integer)
    pa: Mapped[int | None] = mapped_column(Integer)
    spam_score: Mapped[int | None] = mapped_column(Integer)
    semrush_as: Mapped[int | None] = mapped_column(Integer)
    semrush_traffic: Mapped[int | None] = mapped_column(BigInteger)
    semrush_keywords: Mapped[int | None] = mapped_column(Integer)
    domain_created_on: Mapped[date | None] = mapped_column(Date)
    domain_age_days: Mapped[int | None] = mapped_column(Integer)
    metrics_updated_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
