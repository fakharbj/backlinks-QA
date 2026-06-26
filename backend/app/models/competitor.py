"""Competitor backlink analysis (Phase 8 — features 24+).

Lets an agency upload a competitor's backlink list and compare it to the project's
own link profile to surface gaps ("they have a link here, we don't" = an outreach
opportunity). Three tables:

* ``CompetitorSheet``      — one upload batch (paste/CSV) per project.
* ``CompetitorBacklink``   — one competitor link, canonicalised + fingerprinted with
                             the SAME identity system as our own backlinks (so an
                             exact-URL match is detectable), with its registrable
                             source domain stored for aggregation.
* ``CompetitorSourceDomain`` — per (project, registrable domain) rollup with the
                             comparison verdict: EXISTING (we already have a link
                             from this domain) or NEW_OPPORTUNITY (we don't).
"""

from __future__ import annotations

import uuid
from datetime import datetime

from sqlalchemy import (
    Boolean,
    DateTime,
    ForeignKey,
    Index,
    Integer,
    Numeric,
    String,
    UniqueConstraint,
)
from sqlalchemy.dialects.postgresql import UUID as PGUUID
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base, TimestampMixin, UUIDPrimaryKeyMixin


class CompetitorSheet(UUIDPrimaryKeyMixin, TimestampMixin, Base):
    __tablename__ = "competitor_sheets"
    __table_args__ = (Index("ix_competitor_sheets_project", "workspace_id", "project_id"),)

    workspace_id: Mapped[uuid.UUID] = mapped_column(
        PGUUID(as_uuid=True), ForeignKey("workspaces.id", ondelete="CASCADE"), nullable=False
    )
    project_id: Mapped[uuid.UUID] = mapped_column(
        PGUUID(as_uuid=True), ForeignKey("projects.id", ondelete="CASCADE"), nullable=False
    )
    name: Mapped[str] = mapped_column(String(200), nullable=False)
    source_kind: Mapped[str] = mapped_column(String(20), default="paste", nullable=False)
    status: Mapped[str] = mapped_column(String(20), default="ready", nullable=False)
    total_rows: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    domain_count: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    new_domains: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    existing_domains: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    created_by: Mapped[uuid.UUID | None] = mapped_column(PGUUID(as_uuid=True))


class CompetitorBacklink(UUIDPrimaryKeyMixin, TimestampMixin, Base):
    __tablename__ = "competitor_backlinks"
    __table_args__ = (
        Index("ix_competitor_backlinks_sheet", "competitor_sheet_id"),
        Index("ix_competitor_backlinks_project_domain", "project_id", "source_domain"),
    )

    workspace_id: Mapped[uuid.UUID] = mapped_column(PGUUID(as_uuid=True), nullable=False)
    project_id: Mapped[uuid.UUID] = mapped_column(PGUUID(as_uuid=True), nullable=False)
    competitor_sheet_id: Mapped[uuid.UUID] = mapped_column(
        PGUUID(as_uuid=True), ForeignKey("competitor_sheets.id", ondelete="CASCADE"), nullable=False
    )
    canonical_url_id: Mapped[uuid.UUID | None] = mapped_column(PGUUID(as_uuid=True))
    raw_url: Mapped[str] = mapped_column(String(2048), nullable=False)
    source_domain: Mapped[str | None] = mapped_column(String(255))
    anchor: Mapped[str | None] = mapped_column(String(500))
    rel: Mapped[str | None] = mapped_column(String(60))


class CompetitorSourceDomain(UUIDPrimaryKeyMixin, TimestampMixin, Base):
    __tablename__ = "competitor_source_domains"
    __table_args__ = (
        UniqueConstraint("workspace_id", "project_id", "domain_key", name="uq_competitor_src_domain"),
        Index("ix_competitor_src_domains_project", "workspace_id", "project_id", "category"),
    )

    workspace_id: Mapped[uuid.UUID] = mapped_column(PGUUID(as_uuid=True), nullable=False)
    project_id: Mapped[uuid.UUID] = mapped_column(PGUUID(as_uuid=True), nullable=False)
    competitor_sheet_id: Mapped[uuid.UUID | None] = mapped_column(PGUUID(as_uuid=True))
    domain_key: Mapped[str] = mapped_column(String(255), nullable=False)
    url_count: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    # 'existing' (we already link from here) | 'new_opportunity' (we don't yet).
    category: Mapped[str] = mapped_column(String(20), default="new_opportunity", nullable=False)
    our_link_count: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    our_indexed_pct: Mapped[float | None] = mapped_column(Numeric(5, 1))
    is_new: Mapped[bool] = mapped_column(Boolean, default=True, nullable=False)
    last_recomputed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
