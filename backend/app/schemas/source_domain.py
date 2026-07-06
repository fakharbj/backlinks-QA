"""Source main-domain schemas (Phase 8, features 11/12; rules/stats 0033)."""

from __future__ import annotations

import uuid
from datetime import datetime

from pydantic import BaseModel, Field


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
    qualified_count: int = 0
    not_qualified_count: int = 0
    qualified_pct: float = 0.0
    not_qualified_pct: float = 0.0
    referring_domains_count: int = 0
    avg_score: float | None = None
    project_count: int
    user_count: int
    link_type_distribution: dict = {}
    last_recomputed_at: datetime | None = None
    origin: str = "derived"
    da: int | None = None
    pa: int | None = None
    spam_score: int | None = None
    semrush_as: int | None = None
    semrush_traffic: int | None = None
    semrush_keywords: int | None = None
    domain_age_days: int | None = None
    metrics_updated_at: datetime | None = None


class SourceDomainListOut(BaseModel):
    """Paginated list envelope for the Source-Domains desk."""

    items: list[SourceDomainOut] = []
    total: int = 0


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


class SourceDomainStatsOut(BaseModel):
    """One set-based aggregate over the filtered source-domain population."""

    total_domains: int = 0
    total_backlinks: int = 0
    total_qualified: int = 0
    overall_qualified_pct: float = 0.0
    overall_indexed_pct: float = 0.0
    avg_da: float | None = None
    avg_pa: float | None = None
    avg_spam: float | None = None
    avg_as: float | None = None
    count_da_ge_50: int = 0
    count_spam_le_5: int = 0
    # Domain-count of source domains with at least one indexed backlink
    # (NOT backlink-weighted — see source_domain_service.source_domain_stats).
    count_indexed: int = 0


# ── Rules engine ──────────────────────────────────────────────────────────────
class RuleCondition(BaseModel):
    field: str = Field(min_length=1, max_length=40)
    op: str = Field(min_length=1, max_length=10)
    value: float | None = None
    value2: float | None = None
    # For string fields (origin) the operand is carried here.
    value_str: str | None = Field(default=None, max_length=40)


class RuleDefinition(BaseModel):
    match: str = Field(default="all")  # "all" | "any"
    conditions: list[RuleCondition] = []


class SourceDomainRuleCreate(BaseModel):
    name: str = Field(min_length=1, max_length=150)
    description: str | None = Field(default=None, max_length=500)
    project_id: uuid.UUID | None = None
    is_shared: bool = True
    definition: RuleDefinition


class SourceDomainRuleUpdate(BaseModel):
    name: str | None = Field(default=None, min_length=1, max_length=150)
    description: str | None = Field(default=None, max_length=500)
    is_shared: bool | None = None
    definition: RuleDefinition | None = None


class SourceDomainRuleOut(BaseModel):
    id: uuid.UUID
    workspace_id: uuid.UUID
    project_id: uuid.UUID | None = None
    name: str
    description: str | None = None
    definition: dict = {}
    is_shared: bool = True
    created_by: uuid.UUID | None = None
    updated_by: uuid.UUID | None = None
    created_at: datetime | None = None
    updated_at: datetime | None = None
    match_count: int | None = None  # populated by /rules/{id}/apply


# ── Saved filters (per-workspace Setting) ─────────────────────────────────────
class SavedFilterOut(BaseModel):
    name: str
    params: dict = {}


class SavedFilterUpsert(BaseModel):
    name: str = Field(min_length=1, max_length=120)
    params: dict = {}
