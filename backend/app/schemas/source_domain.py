"""Source main-domain schemas (Phase 8, features 11/12)."""

from __future__ import annotations

import uuid
from datetime import datetime

from pydantic import BaseModel


class SourceDomainOut(BaseModel):
    id: uuid.UUID
    domain_key: str
    grouping: str
    backlink_count: int
    indexed_count: int
    not_indexed_count: int
    uncertain_count: int
    unchecked_count: int
    indexed_pct: float
    not_indexed_pct: float
    dofollow_count: int
    nofollow_count: int
    dofollow_pct: float
    duplicate_count: int
    avg_score: float | None = None
    project_count: int
    user_count: int
    link_type_distribution: dict = {}
    last_recomputed_at: datetime | None = None


class SourceDomainBacklinkOut(BaseModel):
    id: uuid.UUID
    project_name: str | None = None
    source_page_url: str
    target_url: str
    status: str | None = None
    score: int | None = None
    link_type: str | None = None
    index_status: str | None = None
    assigned_user_label: str | None = None


class SourceDomainDetailOut(SourceDomainOut):
    backlinks: list[SourceDomainBacklinkOut] = []
