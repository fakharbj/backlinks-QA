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
        # Metric-sort composites for the Source-Domains desk (0033).
        Index("ix_source_domains_ws_da", "workspace_id", "da"),
        Index("ix_source_domains_ws_pa", "workspace_id", "pa"),
        Index("ix_source_domains_ws_spam", "workspace_id", "spam_score"),
        Index("ix_source_domains_ws_as", "workspace_id", "semrush_as"),
        Index("ix_source_domains_ws_qualified", "workspace_id", "qualified_count"),
        # Company dashboard "new source domains" buckets on discovery date (0041).
        Index("ix_source_domains_ws_discovery", "workspace_id", "discovery_date"),
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
    # When this domain first entered the catalog by ANY path (earliest backlink
    # placement, or the import/competitor-promotion date). The dashboard's
    # "new source domains" bucket key. Kept current by recompute + promotion.
    discovery_date: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))

    # ── QA-outcome counters (0033) — STORED, refreshed by recompute ───────────
    # Buckets use the EFFECTIVE status (coalesce(override_status, status));
    # qualified == PASS, not_qualified == everything else. referring_domains_count
    # is the distinct target_domain count for this source domain.
    qualified_count: Mapped[int] = mapped_column(
        Integer, default=0, server_default="0", nullable=False
    )
    not_qualified_count: Mapped[int] = mapped_column(
        Integer, default=0, server_default="0", nullable=False
    )
    warning_count: Mapped[int] = mapped_column(
        Integer, default=0, server_default="0", nullable=False
    )
    fail_count: Mapped[int] = mapped_column(
        Integer, default=0, server_default="0", nullable=False
    )
    pending_count: Mapped[int] = mapped_column(
        Integer, default=0, server_default="0", nullable=False
    )
    referring_domains_count: Mapped[int] = mapped_column(
        Integer, default=0, server_default="0", nullable=False
    )

    # ── Robots rollup (0044) — STORED, refreshed by recompute ─────────────────
    # Buckets over backlink_records.robots_status ('allowed'/'blocked'/'unknown');
    # never-QA'd NULL rows count as unknown so the three buckets sum to
    # backlink_count. robots_band is derived in the same recompute SQL — the
    # ladder lives in source_domain_service.derive_robots_band.
    robots_allowed_count: Mapped[int] = mapped_column(
        Integer, default=0, server_default="0", nullable=False
    )
    robots_blocked_count: Mapped[int] = mapped_column(
        Integer, default=0, server_default="0", nullable=False
    )
    robots_unknown_count: Mapped[int] = mapped_column(
        Integer, default=0, server_default="0", nullable=False
    )
    # unknown | fully_blocked | mostly_blocked | partially_blocked | allowed
    robots_band: Mapped[str | None] = mapped_column(String(20))

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

    # ── First-metrics snapshot (0044) — write-once originals ──────────────────
    # The FIRST da/pa/spam/as/traffic values ever recorded for this domain, so
    # "what did it look like when we found it" survives every later refresh.
    # Filled only while first_metrics_at IS NULL (source_domain_service.
    # apply_first_snapshot / the batch-approve upsert guard); never overwritten.
    da_first: Mapped[int | None] = mapped_column(Integer)
    pa_first: Mapped[int | None] = mapped_column(Integer)
    spam_first: Mapped[int | None] = mapped_column(Integer)
    as_first: Mapped[int | None] = mapped_column(Integer)
    traffic_first: Mapped[int | None] = mapped_column(BigInteger)
    first_metrics_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    # 'checked' = API fetch recorded the first values; 'imported' = they came
    # with an approved import.
    first_metrics_source: Mapped[str | None] = mapped_column(String(12))

    # ── Manual enrichment labels (0044) — user-set, never recomputed ──────────
    market: Mapped[str | None] = mapped_column(String(80))
    country: Mapped[str | None] = mapped_column(String(80))
