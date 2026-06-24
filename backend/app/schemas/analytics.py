"""Analytics request/response schemas (Phase 5)."""

from __future__ import annotations

from typing import Any

from pydantic import BaseModel, Field


class AnalyticsRequest(BaseModel):
    # Whitelisted filter keys → values (unknown keys ignored server-side).
    filters: dict[str, Any] = Field(default_factory=dict)
    # Optional group-by dimension (one of the allowed dimensions).
    group_by: str | None = None
    # Dimensions to return facet counts for (connected filters).
    facets: list[str] = Field(default_factory=list)


class AnalyticsResponse(BaseModel):
    summary: dict[str, Any]
    facets: dict[str, list[dict[str, Any]]]
    groups: list[dict[str, Any]]
    dimensions: list[str]  # allowed group/facet dimensions
