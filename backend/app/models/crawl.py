"""Crawl fact tables.

Scale design (Arch §10):
  * ``crawl_results``   — RANGE-partitioned by month on ``crawled_at``. One row per
    crawl. The full QA verdict (issues, redirect chain, parsed metadata) is stored
    inline as JSONB so each crawl is a self-contained, explainable snapshot; the
    raw HTML body lives in object storage (only a pointer here).
  * ``backlink_history``— RANGE-partitioned by month on ``created_at``. Typed
    change-detection events feeding the timeline and alert rules.
  * ``backlink_issues`` — the *current* issue set per backlink (replaced each
    crawl). Bounded in size, FK-solid, powers grid issue-filters + the detail page.

PostgreSQL requires a partitioned table's primary key to include the partition
column → ``crawl_results`` and ``backlink_history`` use composite PKs.
"""

from __future__ import annotations

import uuid
from datetime import datetime

from sqlalchemy import (
    DateTime,
    Float,
    ForeignKey,
    Index,
    Integer,
    SmallInteger,
    String,
    Text,
    func,
    text,
)
from sqlalchemy.dialects.postgresql import ARRAY, JSONB
from sqlalchemy.dialects.postgresql import UUID as PGUUID
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base, TimestampMixin, UUIDPrimaryKeyMixin
from app.db.types import pg_enum
from app.models.enums import (
    CrawlMode,
    HistoryEventType,
    Indexability,
    IssueCategory,
    JobStatus,
    JobType,
    OverallStatus,
    Severity,
)


class CrawlJob(UUIDPrimaryKeyMixin, TimestampMixin, Base):
    """A logical crawl run (single, bulk, scheduled, or import-triggered)."""

    __tablename__ = "crawl_jobs"
    __table_args__ = (
        Index("ix_crawl_jobs_workspace", "workspace_id"),
        Index("ix_crawl_jobs_project_status", "project_id", "status"),
    )

    workspace_id: Mapped[uuid.UUID] = mapped_column(
        PGUUID(as_uuid=True), ForeignKey("workspaces.id", ondelete="CASCADE"), nullable=False
    )
    project_id: Mapped[uuid.UUID | None] = mapped_column(
        PGUUID(as_uuid=True), ForeignKey("projects.id", ondelete="CASCADE")
    )
    job_type: Mapped[JobType] = mapped_column(pg_enum(JobType, "job_type_enum"), nullable=False)
    status: Mapped[JobStatus] = mapped_column(
        pg_enum(JobStatus, "job_status_enum"), default=JobStatus.PENDING, nullable=False
    )
    triggered_by: Mapped[uuid.UUID | None] = mapped_column(
        PGUUID(as_uuid=True), ForeignKey("users.id", ondelete="SET NULL")
    )
    total: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    processed: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    succeeded: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    failed: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    started_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    finished_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    params: Mapped[dict] = mapped_column(JSONB, default=dict)
    error: Mapped[str | None] = mapped_column(Text)


class CrawlResult(Base):
    __tablename__ = "crawl_results"
    __table_args__ = (
        Index("ix_crawl_results_backlink", "backlink_id", "crawled_at"),
        Index("ix_crawl_results_job", "crawl_job_id"),
        Index("ix_crawl_results_workspace_time", "workspace_id", "crawled_at"),
        {"postgresql_partition_by": "RANGE (crawled_at)"},
    )

    id: Mapped[uuid.UUID] = mapped_column(
        PGUUID(as_uuid=True), primary_key=True, server_default=text("gen_random_uuid()")
    )
    crawled_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), primary_key=True, server_default=func.now()
    )

    backlink_id: Mapped[uuid.UUID] = mapped_column(PGUUID(as_uuid=True), nullable=False)
    workspace_id: Mapped[uuid.UUID] = mapped_column(PGUUID(as_uuid=True), nullable=False)
    project_id: Mapped[uuid.UUID] = mapped_column(PGUUID(as_uuid=True), nullable=False)
    crawl_job_id: Mapped[uuid.UUID | None] = mapped_column(PGUUID(as_uuid=True))

    # ── Transport / response ─────────────────────────────────────────────────
    crawl_mode: Mapped[CrawlMode] = mapped_column(
        pg_enum(CrawlMode, "crawl_mode_enum"), default=CrawlMode.RAW, nullable=False
    )
    http_status: Mapped[int | None] = mapped_column(SmallInteger)
    final_url: Mapped[str | None] = mapped_column(String(2048))
    content_type: Mapped[str | None] = mapped_column(String(255))
    content_length: Mapped[int | None] = mapped_column(Integer)
    encoding: Mapped[str | None] = mapped_column(String(40))
    response_headers: Mapped[dict] = mapped_column(JSONB, default=dict)
    redirect_chain: Mapped[list] = mapped_column(JSONB, default=list)  # [{url,status},...]
    crawl_duration_ms: Mapped[int | None] = mapped_column(Integer)
    fetch_error: Mapped[str | None] = mapped_column(String(120))

    # ── Parsed signals ───────────────────────────────────────────────────────
    link_found: Mapped[bool | None] = mapped_column()
    found_in_raw: Mapped[bool | None] = mapped_column()
    found_in_rendered: Mapped[bool | None] = mapped_column()
    matched_href: Mapped[str | None] = mapped_column(String(2048))
    anchor_text: Mapped[str | None] = mapped_column(Text)
    rel_values: Mapped[list[str]] = mapped_column(ARRAY(String), default=list)
    link_context: Mapped[str | None] = mapped_column(Text)
    link_region: Mapped[str | None] = mapped_column(String(40))
    meta_robots: Mapped[str | None] = mapped_column(String(400))
    x_robots_tag: Mapped[str | None] = mapped_column(String(400))
    canonical_url: Mapped[str | None] = mapped_column(String(2048))
    robots_allowed: Mapped[bool | None] = mapped_column()
    page_title: Mapped[str | None] = mapped_column(Text)
    word_count: Mapped[int | None] = mapped_column(Integer)
    language: Mapped[str | None] = mapped_column(String(20))
    outbound_link_count: Mapped[int | None] = mapped_column(Integer)
    page_signals: Mapped[dict] = mapped_column(JSONB, default=dict)

    # ── QA verdict snapshot ──────────────────────────────────────────────────
    status: Mapped[OverallStatus] = mapped_column(
        pg_enum(OverallStatus, "overall_status_enum", create_type=False), nullable=False
    )
    score: Mapped[int] = mapped_column(SmallInteger, nullable=False)
    score_breakdown: Mapped[list] = mapped_column(JSONB, default=list)
    is_followable: Mapped[bool | None] = mapped_column()
    is_indexable: Mapped[Indexability | None] = mapped_column(
        pg_enum(Indexability, "indexability_enum", create_type=False)
    )
    # The scoring rule set version that produced this verdict (Phase 8 F17). Added
    # in migration 0016; nullable so pre-Phase-8 historical rows resolve to global v1.
    scoring_rule_version_id: Mapped[uuid.UUID | None] = mapped_column(PGUUID(as_uuid=True))
    issues: Mapped[list] = mapped_column(JSONB, default=list)  # full issue snapshot
    recommendations: Mapped[list] = mapped_column(JSONB, default=list)

    # ── Object-storage pointers ──────────────────────────────────────────────
    raw_html_key: Mapped[str | None] = mapped_column(String(500))
    rendered_html_key: Mapped[str | None] = mapped_column(String(500))


class BacklinkIssue(UUIDPrimaryKeyMixin, Base):
    """Current issue set for a backlink (replaced wholesale on each crawl)."""

    __tablename__ = "backlink_issues"
    __table_args__ = (
        Index("ix_backlink_issues_backlink", "backlink_id"),
        Index("ix_backlink_issues_workspace_label", "workspace_id", "label"),
        Index("ix_backlink_issues_project_severity", "project_id", "severity"),
        Index("ix_backlink_issues_code", "code"),
    )

    backlink_id: Mapped[uuid.UUID] = mapped_column(
        PGUUID(as_uuid=True),
        ForeignKey("backlink_records.id", ondelete="CASCADE"),
        nullable=False,
    )
    workspace_id: Mapped[uuid.UUID] = mapped_column(PGUUID(as_uuid=True), nullable=False)
    project_id: Mapped[uuid.UUID] = mapped_column(PGUUID(as_uuid=True), nullable=False)
    crawl_result_id: Mapped[uuid.UUID | None] = mapped_column(PGUUID(as_uuid=True))

    code: Mapped[str] = mapped_column(String(20), nullable=False)  # e.g. "HTTP-404"
    label: Mapped[str] = mapped_column(String(60), nullable=False)
    category: Mapped[IssueCategory] = mapped_column(
        pg_enum(IssueCategory, "issue_category_enum"), nullable=False
    )
    severity: Mapped[Severity] = mapped_column(
        pg_enum(Severity, "severity_enum"), nullable=False
    )
    message: Mapped[str] = mapped_column(Text, nullable=False)
    recommendation: Mapped[str | None] = mapped_column(Text)
    evidence: Mapped[dict] = mapped_column(JSONB, default=dict)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )


class BacklinkHistory(Base):
    __tablename__ = "backlink_history"
    __table_args__ = (
        Index("ix_backlink_history_backlink", "backlink_id", "created_at"),
        Index("ix_backlink_history_workspace_time", "workspace_id", "created_at"),
        Index("ix_backlink_history_event", "event_type"),
        {"postgresql_partition_by": "RANGE (created_at)"},
    )

    id: Mapped[uuid.UUID] = mapped_column(
        PGUUID(as_uuid=True), primary_key=True, server_default=text("gen_random_uuid()")
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), primary_key=True, server_default=func.now()
    )

    backlink_id: Mapped[uuid.UUID] = mapped_column(PGUUID(as_uuid=True), nullable=False)
    workspace_id: Mapped[uuid.UUID] = mapped_column(PGUUID(as_uuid=True), nullable=False)
    project_id: Mapped[uuid.UUID] = mapped_column(PGUUID(as_uuid=True), nullable=False)
    crawl_result_id: Mapped[uuid.UUID | None] = mapped_column(PGUUID(as_uuid=True))

    event_type: Mapped[HistoryEventType] = mapped_column(
        pg_enum(HistoryEventType, "history_event_type_enum"), nullable=False
    )
    severity: Mapped[Severity | None] = mapped_column(
        pg_enum(Severity, "severity_enum", create_type=False)
    )
    field: Mapped[str | None] = mapped_column(String(60))
    old_value: Mapped[str | None] = mapped_column(Text)
    new_value: Mapped[str | None] = mapped_column(Text)
    score_delta: Mapped[float | None] = mapped_column(Float)
    detail: Mapped[dict] = mapped_column(JSONB, default=dict)
