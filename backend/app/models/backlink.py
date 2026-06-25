"""``backlink_records`` — the system of record for every monitored link.

Holds three logical groups of columns:
  1. *Expected* (contract) fields, as imported.
  2. *Normalized* forms used for fast matching/indexing (PRD §8.4).
  3. *Observed/current* verdict denormalised from the latest crawl for grid speed.

The heavy fact tables (``crawl_results``, ``backlink_history``) reference this row.
"""

from __future__ import annotations

import uuid
from datetime import date, datetime

from sqlalchemy import (
    CheckConstraint,
    Date,
    DateTime,
    ForeignKey,
    Index,
    Integer,
    Numeric,
    SmallInteger,
    String,
    Text,
    UniqueConstraint,
    text,
)
from sqlalchemy.dialects.postgresql import ARRAY, JSONB
from sqlalchemy.dialects.postgresql import UUID as PGUUID
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base, TimestampMixin, UUIDPrimaryKeyMixin
from app.db.types import pg_enum
from app.models.enums import (
    ExternalIndexStatus,
    Indexability,
    OverallStatus,
    RelType,
)


class BacklinkRecord(UUIDPrimaryKeyMixin, TimestampMixin, Base):
    __tablename__ = "backlink_records"
    __table_args__ = (
        # Phase 8 F10: duplicates are STORED (not skipped) and grouped by canonical
        # fingerprint into conflicts. A sheet row stays idempotent on re-sync via its
        # sheet position, so syncs update in place instead of multiplying rows.
        Index(
            "uq_backlink_records_sheet_entry",
            "source_sheet_id",
            "sheet_tab",
            "sheet_row_ref",
            unique=True,
            postgresql_where=text("source_sheet_id IS NOT NULL"),
        ),
        # Tenant + scoping
        Index("ix_backlink_records_workspace", "workspace_id"),
        Index("ix_backlink_records_project", "project_id"),
        # Matching / lookups
        Index("ix_backlink_records_source_norm", "source_url_normalized"),
        Index("ix_backlink_records_target_norm", "target_url_normalized"),
        Index("ix_backlink_records_source_domain", "source_domain"),
        # Filtering / sorting
        Index("ix_backlink_records_status", "status"),
        Index("ix_backlink_records_score", "score"),
        Index("ix_backlink_records_last_checked", "last_checked_at"),
        Index("ix_backlink_records_next_check", "next_check_at"),
        # Grid grid composite + keyset
        Index("ix_backlink_records_grid", "project_id", "status", "score"),
        Index("ix_backlink_records_keyset", "project_id", "score", "id"),
        # Fast failure view (partial index) — PRD §28 / Arch §10
        Index(
            "ix_backlink_records_failed",
            "project_id",
            "score",
            postgresql_where=text("status = 'FAIL'"),
        ),
        Index("ix_backlink_records_vendor", "vendor_id"),
        Index("ix_backlink_records_campaign", "campaign_id"),
        Index("ix_backlink_records_tags", "tags", postgresql_using="gin"),
        Index("ix_backlink_records_source_sheet", "source_sheet_id"),
        Index("ix_backlink_records_assigned_label", "assigned_user_label"),
        Index("ix_backlink_records_link_type", "link_type"),
        Index("ix_backlink_records_link_type_id", "link_type_id"),
        Index("ix_backlink_records_identity", "link_identity_id"),
        Index("ix_backlink_records_canonical_url", "canonical_url_id"),
        Index("ix_backlink_records_source_domain_id", "source_domain_id"),
        Index("ix_backlink_records_duplicate", "workspace_id", "duplicate_status"),
        Index("ix_backlink_records_index_status", "workspace_id", "index_status"),
        Index("ix_backlink_records_index_due", "index_checked_at"),
        CheckConstraint("score >= 0 AND score <= 100", name="score_range"),
    )

    workspace_id: Mapped[uuid.UUID] = mapped_column(
        PGUUID(as_uuid=True), ForeignKey("workspaces.id", ondelete="CASCADE"), nullable=False
    )
    project_id: Mapped[uuid.UUID] = mapped_column(
        PGUUID(as_uuid=True), ForeignKey("projects.id", ondelete="CASCADE"), nullable=False
    )
    vendor_id: Mapped[uuid.UUID | None] = mapped_column(
        PGUUID(as_uuid=True), ForeignKey("vendors.id", ondelete="SET NULL")
    )
    campaign_id: Mapped[uuid.UUID | None] = mapped_column(
        PGUUID(as_uuid=True), ForeignKey("campaigns.id", ondelete="SET NULL")
    )
    assigned_user_id: Mapped[uuid.UUID | None] = mapped_column(
        PGUUID(as_uuid=True), ForeignKey("users.id", ondelete="SET NULL")
    )
    import_id: Mapped[uuid.UUID | None] = mapped_column(
        PGUUID(as_uuid=True), ForeignKey("imports.id", ondelete="SET NULL")
    )

    # ── Expected / contract fields (as imported) ─────────────────────────────
    source_page_url: Mapped[str] = mapped_column(String(2048), nullable=False)
    target_url: Mapped[str] = mapped_column(String(2048), nullable=False)
    expected_target_url: Mapped[str | None] = mapped_column(String(2048))
    expected_anchor_text: Mapped[str | None] = mapped_column(Text)
    expected_rel: Mapped[RelType] = mapped_column(
        pg_enum(RelType, "rel_type_enum"), default=RelType.DOFOLLOW, nullable=False
    )
    client_name: Mapped[str | None] = mapped_column(String(200))
    cost: Mapped[float | None] = mapped_column(Numeric(12, 2))
    placement_date: Mapped[date | None] = mapped_column(Date)
    expected_status: Mapped[str | None] = mapped_column(String(40), default="live")
    notes: Mapped[str | None] = mapped_column(Text)
    tags: Mapped[list[str]] = mapped_column(ARRAY(String), default=list)

    # ── Sheet-sourced input fields (Phase 2) ─────────────────────────────────
    # The sheet is the source of truth for these; QA/result fields are owned by DB.
    assigned_user_label: Mapped[str | None] = mapped_column(String(200))  # sheet "User"
    employee_code: Mapped[str | None] = mapped_column(String(60))
    link_type: Mapped[str | None] = mapped_column(String(60))             # free text (raw)
    link_type_id: Mapped[uuid.UUID | None] = mapped_column(PGUUID(as_uuid=True))  # catalog (Phase 8)
    source_sheet_id: Mapped[uuid.UUID | None] = mapped_column(
        PGUUID(as_uuid=True), ForeignKey("sheet_sources.id", ondelete="SET NULL")
    )
    sheet_row_ref: Mapped[str | None] = mapped_column(String(40))         # row number for write-back
    sheet_tab: Mapped[str | None] = mapped_column(String(200))            # sub-sheet/tab name (Phase 8)
    sheet_created_date: Mapped[date | None] = mapped_column(Date)

    # ── Canonical identity (Phase 8) — global fingerprint of the source URL ───
    # FK to canonical_urls (sha256 of the normalized URL). Populated by the 0007
    # backfill; the import/conflict wiring that reads it lands in a later increment.
    canonical_url_id: Mapped[uuid.UUID | None] = mapped_column(PGUUID(as_uuid=True))

    # ── Source-domain aggregate link (Phase 8 F11) ───────────────────────────
    source_domain_id: Mapped[uuid.UUID | None] = mapped_column(PGUUID(as_uuid=True))

    # ── Duplicate detection (Phase 3) ────────────────────────────────────────
    # Identity = (source_url_normalized, target_domain) per workspace.
    link_identity_id: Mapped[uuid.UUID | None] = mapped_column(PGUUID(as_uuid=True))
    is_duplicate: Mapped[bool] = mapped_column(default=False, nullable=False)
    # unique | dup_cross_project | dup_cross_user | dup_same_project
    duplicate_status: Mapped[str | None] = mapped_column(String(40))

    # ── Index status (Phase 4) — denormalised from the latest source-URL check ─
    index_status: Mapped[str | None] = mapped_column(String(20))  # indexed|not_indexed|uncertain
    index_result_count: Mapped[int | None] = mapped_column(Integer)
    index_checked_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))

    # ── Normalized forms (matching/indexing) ─────────────────────────────────
    source_url_normalized: Mapped[str] = mapped_column(String(2048), nullable=False)
    target_url_normalized: Mapped[str] = mapped_column(String(2048), nullable=False)
    source_domain: Mapped[str] = mapped_column(String(255), nullable=False)  # registrable
    target_domain: Mapped[str | None] = mapped_column(String(255))

    # ── Observed / current verdict (denormalised from latest crawl) ──────────
    status: Mapped[OverallStatus] = mapped_column(
        pg_enum(OverallStatus, "overall_status_enum"),
        default=OverallStatus.PENDING,
        nullable=False,
    )
    score: Mapped[int | None] = mapped_column(SmallInteger)
    link_found: Mapped[bool | None] = mapped_column()
    current_rel: Mapped[RelType | None] = mapped_column(
        pg_enum(RelType, "rel_type_enum", create_type=False)
    )
    current_anchor_text: Mapped[str | None] = mapped_column(Text)
    http_status: Mapped[int | None] = mapped_column(SmallInteger)
    final_url: Mapped[str | None] = mapped_column(String(2048))
    indexability: Mapped[Indexability | None] = mapped_column(
        pg_enum(Indexability, "indexability_enum")
    )
    external_index_status: Mapped[ExternalIndexStatus | None] = mapped_column(
        pg_enum(ExternalIndexStatus, "external_index_status_enum")
    )
    canonical_status: Mapped[str | None] = mapped_column(String(40))
    robots_status: Mapped[str | None] = mapped_column(String(40))
    issue_count: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    top_issue_label: Mapped[str | None] = mapped_column(String(60))

    latest_crawl_result_id: Mapped[uuid.UUID | None] = mapped_column(PGUUID(as_uuid=True))
    # The scoring rule set version that produced the current score/status (Phase 8 F17).
    scoring_rule_version_id: Mapped[uuid.UUID | None] = mapped_column(PGUUID(as_uuid=True))
    last_checked_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    next_check_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    consecutive_failures: Mapped[int] = mapped_column(SmallInteger, default=0, nullable=False)

    # ── Manual override (PRD §8.15) ──────────────────────────────────────────
    override_status: Mapped[OverallStatus | None] = mapped_column(
        pg_enum(OverallStatus, "overall_status_enum", create_type=False)
    )
    override_note: Mapped[str | None] = mapped_column(Text)
    overridden_by: Mapped[uuid.UUID | None] = mapped_column(
        PGUUID(as_uuid=True), ForeignKey("users.id", ondelete="SET NULL")
    )
    overridden_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))

    # Free-form extension bag (e.g. third-party metric enrichment later).
    extra: Mapped[dict] = mapped_column(JSONB, default=dict)

    @property
    def effective_status(self) -> OverallStatus:
        return self.override_status or self.status
