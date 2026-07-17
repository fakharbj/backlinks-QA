"""Conflict (duplicate group) schemas (Phase 8, feature 9; enterprise 0034)."""

from __future__ import annotations

import uuid
from datetime import date, datetime
from typing import Any

from pydantic import BaseModel


class ConflictMemberOut(BaseModel):
    backlink_id: uuid.UUID
    project_id: uuid.UUID | None = None
    project_name: str | None = None
    source_page_url: str
    target_url: str
    status: str | None = None
    score: int | None = None
    assigned_user_label: str | None = None
    link_type: str | None = None
    # ── Enriched comparison fields (0034) ────────────────────────────────────
    source_domain: str | None = None
    current_anchor_text: str | None = None
    expected_anchor_text: str | None = None
    current_rel: str | None = None
    expected_rel: str | None = None
    target_url_normalized: str | None = None
    target_domain: str | None = None
    index_status: str | None = None
    duplicate_status: str | None = None
    is_duplicate: bool | None = None
    placement_date: date | None = None
    created_at: datetime | None = None
    last_checked_at: datetime | None = None
    override_status: str | None = None


class ConflictOut(BaseModel):
    id: uuid.UUID
    canonical_url: str | None = None
    fingerprint: str | None = None
    project_id: uuid.UUID | None = None
    scope: str
    resolution_status: str
    member_count: int
    detected_at: datetime | None = None
    created_at: datetime | None = None
    # ── Enterprise facts (0034) ──────────────────────────────────────────────
    reason: str | None = None
    similarity: int | None = None
    first_member_id: uuid.UUID | None = None
    distinct_projects: int | None = None
    distinct_users: int | None = None
    distinct_targets: int | None = None
    members: list[ConflictMemberOut] = []


class ConflictAggregatesOut(BaseModel):
    """Filter-scoped KPI numbers — computed over the SAME where-clause as the
    page, so cards and table can never disagree."""

    open: int = 0
    resolved: int = 0
    total_duplicate_links: int = 0
    avg_similarity: float | None = None


class ConflictListOut(BaseModel):
    """Paginated list envelope (offset + total)."""

    items: list[ConflictOut] = []
    total: int = 0
    limit: int = 100
    offset: int = 0
    aggregates: ConflictAggregatesOut = ConflictAggregatesOut()


class FieldMatrixRow(BaseModel):
    field: str
    all_same: bool
    distinct: int
    values: list[Any] = []


class ConflictActionOut(BaseModel):
    id: uuid.UUID
    action: str
    payload: dict = {}
    actor_user_id: uuid.UUID | None = None
    note: str | None = None
    created_at: datetime | None = None


class ConflictDetailOut(ConflictOut):
    field_matrix: list[FieldMatrixRow] = []
    suggested_keep: uuid.UUID | None = None
    actions: list[ConflictActionOut] = []
    # When a huge group is capped, how many members exist in total.
    total_members: int = 0
    members_truncated: bool = False


class ConflictSummaryOut(BaseModel):
    total: int = 0
    open: int = 0
    resolved: int = 0
    by_scope: dict[str, int] = {}
    # Full resolution_status → count map (open/acknowledged/resolved/ignored/…).
    by_status: dict[str, int] = {}
    avg_similarity: float | None = None
    # Total redundant links = sum(member_count - 1) across all groups.
    total_duplicate_links: int = 0
    # Duplicate groups first found per week (last 12 weeks) — for the trend chart.
    weekly: list[dict] = []


class ConflictResolve(BaseModel):
    resolution_status: str  # open | acknowledged | resolved | ignored


class ConflictKeepOne(BaseModel):
    keep_backlink_id: uuid.UUID


class ConflictReassign(BaseModel):
    to_user_label: str


class ConflictBulk(BaseModel):
    conflict_ids: list[uuid.UUID] = []
    action: str  # resolve | acknowledge | ignore | reopen
