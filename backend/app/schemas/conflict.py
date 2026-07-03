"""Conflict (duplicate group) schemas (Phase 8, feature 9)."""

from __future__ import annotations

import uuid
from datetime import datetime

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
    members: list[ConflictMemberOut] = []


class ConflictSummaryOut(BaseModel):
    total: int = 0
    open: int = 0
    resolved: int = 0
    by_scope: dict[str, int] = {}
    # Duplicate groups first found per week (last 12 weeks) — for the trend chart.
    weekly: list[dict] = []


class ConflictResolve(BaseModel):
    resolution_status: str  # open | acknowledged | resolved | ignored
