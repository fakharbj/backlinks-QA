"""Backlink schemas: grid row, detail, filters, override, recheck."""

from __future__ import annotations

import uuid
from datetime import date, datetime
from typing import Any, Literal

from pydantic import BaseModel, Field

from app.models.enums import Indexability, OverallStatus, RelType
from app.schemas.common import ORMModel


class BacklinkCreate(BaseModel):
    project_id: uuid.UUID
    source_page_url: str
    target_url: str
    expected_target_url: str | None = None
    expected_anchor_text: str | None = None
    expected_rel: RelType = RelType.DOFOLLOW
    vendor: str | None = None
    campaign: str | None = None
    client_name: str | None = None
    cost: float | None = None
    placement_date: date | None = None
    notes: str | None = None
    tags: list[str] = Field(default_factory=list)


class BacklinkUpdate(BaseModel):
    expected_target_url: str | None = None
    expected_anchor_text: str | None = None
    expected_rel: RelType | None = None
    notes: str | None = None
    tags: list[str] | None = None
    assigned_user_id: uuid.UUID | None = None
    vendor_id: uuid.UUID | None = None
    campaign_id: uuid.UUID | None = None


class BacklinkOverride(BaseModel):
    status: OverallStatus
    note: str = Field(min_length=1, max_length=2000)


class BacklinkRow(ORMModel):
    id: uuid.UUID
    project_id: uuid.UUID
    source_page_url: str
    target_url: str
    status: OverallStatus
    override_status: OverallStatus | None
    score: int | None
    link_found: bool | None
    current_rel: RelType | None
    current_anchor_text: str | None
    http_status: int | None
    indexability: Indexability | None
    canonical_status: str | None
    robots_status: str | None
    issue_count: int
    top_issue_label: str | None
    created_at: datetime | None = None
    last_checked_at: datetime | None
    next_check_at: datetime | None
    assigned_user_id: uuid.UUID | None
    assigned_user_label: str | None = None
    employee_code: str | None = None
    link_type: str | None = None
    is_duplicate: bool = False
    duplicate_status: str | None = None
    index_status: str | None = None
    tags: list[str]
    extra: dict[str, Any] = Field(default_factory=dict)  # carries extra["metrics"]


class IssueOut(BaseModel):
    code: str
    label: str
    category: str
    severity: str
    message: str
    recommendation: str | None
    evidence: dict[str, Any] = Field(default_factory=dict)


class HistoryEventOut(BaseModel):
    event_type: str
    severity: str | None
    field: str | None
    old_value: str | None
    new_value: str | None
    score_delta: float | None
    created_at: datetime


class CrawlResultOut(BaseModel):
    id: uuid.UUID
    crawled_at: datetime
    crawl_mode: str
    http_status: int | None
    final_url: str | None
    content_type: str | None
    redirect_chain: list[dict[str, Any]]
    meta_robots: str | None
    x_robots_tag: str | None
    canonical_url: str | None
    anchor_text: str | None
    rel_values: list[str]
    status: str
    score: int
    is_followable: bool | None
    is_indexable: str | None
    score_breakdown: list[dict[str, Any]]
    word_count: int | None
    outbound_link_count: int | None
    published_date: str | None = None
    modified_date: str | None = None
    date_source: str | None = None
    raw_html_key: str | None
    rendered_html_key: str | None


class BacklinkDetail(BacklinkRow):
    expected_target_url: str | None
    expected_anchor_text: str | None
    expected_rel: RelType
    final_url: str | None
    source_domain: str
    target_domain: str | None
    override_note: str | None
    notes: str | None
    issues: list[IssueOut] = Field(default_factory=list)
    recommendations: list[str] = Field(default_factory=list)
    score_breakdown: list[dict[str, Any]] = Field(default_factory=list)
    latest_result: CrawlResultOut | None = None
    history: list[HistoryEventOut] = Field(default_factory=list)


class BacklinkFilters(BaseModel):
    """Grid filters. ``status``/``rel``/``link_type``/``index_status``/
    ``duplicate_status``/``assigned_user_label``/``source_domain`` accept a single
    value OR a comma-separated multi-select list; the sentinel ``(blanks)``
    matches NULL/empty (see ``backlink_service._apply_filters``)."""

    project_id: uuid.UUID | None = None
    status: str | None = None
    issue_label: str | None = None
    score_min: int | None = Field(default=None, ge=0, le=100)
    score_max: int | None = Field(default=None, ge=0, le=100)
    rel: str | None = None
    indexability: Indexability | None = None
    robots_status: str | None = None
    canonical_status: str | None = None
    vendor_id: uuid.UUID | None = None
    campaign_id: uuid.UUID | None = None
    tag: str | None = None
    source_domain: str | None = None
    assigned_user_id: uuid.UUID | None = None
    assigned_user_label: str | None = None
    link_type: str | None = None
    duplicate_status: str | None = None  # "duplicate" (any) | a specific status
    index_status: str | None = None      # indexed | not_indexed | uncertain | unchecked
    search: str | None = None


class AssignmentEventOut(BaseModel):
    old_user_label: str | None
    new_user_label: str | None
    source: str
    changed_at: datetime


class RecheckRequest(BaseModel):
    backlink_ids: list[uuid.UUID] | None = None
    project_id: uuid.UUID | None = None
    vendor_id: uuid.UUID | None = None
    campaign_id: uuid.UUID | None = None
    only_failed: bool = False
    only_warnings: bool = False
    priority: bool = False
    # Freshness-based recheck: only links last checked more than N days ago
    # (or never checked). None/0 = no freshness constraint (force everything).
    older_than_days: int | None = Field(default=None, ge=1, le=365)


class RecheckResponse(BaseModel):
    job_id: uuid.UUID
    queued: int


SortField = Literal["score", "last_checked_at", "created_at"]
