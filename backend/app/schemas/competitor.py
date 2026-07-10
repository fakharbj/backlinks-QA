"""Competitor analysis schemas (Phase 8)."""

from __future__ import annotations

import uuid
from datetime import datetime

from pydantic import BaseModel, Field

from app.schemas.common import ORMModel


class CompetitorIngestRequest(BaseModel):
    project_id: uuid.UUID
    # The competitor's site URL is the upload's identity (required); the name is
    # optional — the UI falls back to the URL's domain.
    competitor_url: str = Field(min_length=4, max_length=500)
    name: str = Field(default="", max_length=200)
    text: str


class CompetitorPreviewRequest(BaseModel):
    text: str


class CompetitorPreviewOut(BaseModel):
    format: str                     # semrush | headers | plain
    mapping: dict[str, str]         # detected column → field
    row_count: int
    sample: list[dict]              # first rows as parsed (url/anchor/rel/link_type)
    warnings: list[str] = Field(default_factory=list)


class CompetitorSheetOut(ORMModel):
    id: uuid.UUID
    name: str
    competitor_url: str | None = None
    source_kind: str
    status: str
    total_rows: int
    domain_count: int
    new_domains: int
    existing_domains: int
    created_at: datetime


class CompetitorDomainOut(BaseModel):
    id: str
    domain_key: str
    url_count: int
    category: str
    our_link_count: int
    our_indexed_pct: float | None
    is_new: bool
    da: int | None = None           # checked (or reused from our own domains)
    pa: int | None = None
    decision: str = "open"          # workflow status (new/under_review/…; survives recompute)
    decision_reason: str | None = None
    has_guest_post: bool = False
    # Phase 10 P2: opportunity-workflow assignment (who owns this domain's review).
    status: str | None = None
    assigned_to: uuid.UUID | None = None


class CompetitorDecisionRequest(BaseModel):
    project_id: uuid.UUID
    domain_key: str
    status: str  # dismissed | open
    reason: str | None = None


class CompetitorSummary(BaseModel):
    domains: int = 0
    new_opportunities: int = 0
    existing: int = 0
    dismissed: int = 0
    competitor_links: int = 0
    avg_da: int | None = None       # avg checked DA across domains (null until checked)
    avg_as: int | None = None       # avg SEMrush Authority Score (from our own catalog)
