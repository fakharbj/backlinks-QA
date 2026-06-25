"""Dashboard schemas (PRD §8.13)."""

from __future__ import annotations

import uuid
from datetime import datetime

from pydantic import BaseModel, Field


class StatusTotals(BaseModel):
    total: int = 0
    pass_count: int = 0
    warning_count: int = 0
    fail_count: int = 0
    unknown_count: int = 0
    review_count: int = 0
    pending_count: int = 0
    avg_score: float | None = None


class IssueTotals(BaseModel):
    nofollow_count: int = 0
    noindex_count: int = 0
    robots_blocked_count: int = 0
    canonical_issue_count: int = 0
    broken_count: int = 0
    link_missing_count: int = 0


class LostWindow(BaseModel):
    today: int = 0
    week: int = 0
    month: int = 0


class DomainFailure(BaseModel):
    source_domain: str
    total: int
    fail_count: int
    failure_rate: float | None


class VendorFailure(BaseModel):
    vendor_id: uuid.UUID
    vendor_name: str | None
    total: int
    fail_count: int
    failure_rate: float | None
    avg_score: float | None


class RecentChange(BaseModel):
    backlink_id: uuid.UUID
    source_page_url: str
    event_type: str
    severity: str | None
    created_at: datetime


# ── Project-dashboard-only sections (Phase 8) ────────────────────────────────
class LinkTypeBreakdown(BaseModel):
    link_type: str
    total: int
    pass_count: int
    fail_count: int
    avg_score: float | None = None


class TrendPoint(BaseModel):
    date: str
    added: int
    removed: int
    score_changed: int


class TopSourceDomain(BaseModel):
    source_domain: str
    total: int
    pass_count: int
    fail_count: int
    indexed_pct: float | None = None


class RecentRegression(BaseModel):
    backlink_id: uuid.UUID
    source_page_url: str
    event_type: str
    severity: str | None
    field: str | None
    old_value: str | None
    new_value: str | None
    created_at: datetime


class AssignedUserStat(BaseModel):
    assigned_user_label: str
    total: int
    pass_count: int
    fail_count: int
    avg_score: float | None = None


class DashboardResponse(BaseModel):
    totals: StatusTotals
    issues: IssueTotals
    lost: LostWindow
    top_failing_domains: list[DomainFailure]
    top_vendors_by_failure: list[VendorFailure]
    recent_changes: list[RecentChange]
    # Populated only for a single-project dashboard (empty for the company view).
    is_project: bool = False
    link_type_breakdown: list[LinkTypeBreakdown] = Field(default_factory=list)
    trends: list[TrendPoint] = Field(default_factory=list)
    top_source_domains: list[TopSourceDomain] = Field(default_factory=list)
    recent_regressions: list[RecentRegression] = Field(default_factory=list)
    assigned_user_stats: list[AssignedUserStat] = Field(default_factory=list)
