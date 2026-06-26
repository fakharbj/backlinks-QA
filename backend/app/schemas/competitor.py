"""Competitor analysis schemas (Phase 8)."""

from __future__ import annotations

import uuid
from datetime import datetime

from pydantic import BaseModel, Field

from app.schemas.common import ORMModel


class CompetitorIngestRequest(BaseModel):
    project_id: uuid.UUID
    name: str = Field(default="Competitor upload", max_length=200)
    text: str


class CompetitorSheetOut(ORMModel):
    id: uuid.UUID
    name: str
    source_kind: str
    status: str
    total_rows: int
    domain_count: int
    new_domains: int
    existing_domains: int
    created_at: datetime


class CompetitorDomainOut(ORMModel):
    id: uuid.UUID
    domain_key: str
    url_count: int
    category: str
    our_link_count: int
    our_indexed_pct: float | None
    is_new: bool


class CompetitorSummary(BaseModel):
    domains: int = 0
    new_opportunities: int = 0
    existing: int = 0
    competitor_links: int = 0
