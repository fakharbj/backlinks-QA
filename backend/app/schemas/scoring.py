"""Dynamic scoring config schemas (Phase 8 F17–19)."""

from __future__ import annotations

import uuid
from datetime import datetime

from pydantic import BaseModel


class ScoringParameterOut(BaseModel):
    key: str
    display_name: str
    description: str | None = None
    category: str
    value_kind: str
    outcomes: list[dict]
    default_points: dict
    sort_order: int


class ScoringConfigOut(BaseModel):
    scope: str
    scope_ref_id: uuid.UUID | None
    link_type_id: uuid.UUID | None = None
    version: int
    version_id: uuid.UUID | None
    rules: dict
    bands: dict
    inherited_rules: dict
    inherited_bands: dict
    note: str | None = None
    parameters: list[ScoringParameterOut]


class ScoringConfigSave(BaseModel):
    scope: str
    scope_ref_id: uuid.UUID | None = None
    link_type_id: uuid.UUID | None = None  # project_link_type scope only
    rules: dict
    bands: dict | None = None
    note: str | None = None


class ScoringVersionOut(BaseModel):
    id: uuid.UUID
    scope: str
    scope_ref_id: uuid.UUID | None
    version: int
    is_latest: bool
    note: str | None = None
    created_at: datetime


class RescoreRequest(BaseModel):
    scope: str
    scope_ref_id: uuid.UUID | None = None
    link_type_id: uuid.UUID | None = None  # project_link_type scope only
    preview: bool = True


class RescoreResult(BaseModel):
    scope: str
    applied: bool
    total: int
    changed: int
    avg_score_delta: float
    transitions: dict
