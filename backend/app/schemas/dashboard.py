"""Dashboard schemas (PRD §8.13)."""

from __future__ import annotations

import uuid
from datetime import datetime

from pydantic import BaseModel


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


class DashboardResponse(BaseModel):
    totals: StatusTotals
    issues: IssueTotals
    lost: LostWindow
    top_failing_domains: list[DomainFailure]
    top_vendors_by_failure: list[VendorFailure]
    recent_changes: list[RecentChange]
