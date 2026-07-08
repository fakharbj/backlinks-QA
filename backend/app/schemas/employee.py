"""Employee code + mapping schemas (Phase 8, feature 3)."""

from __future__ import annotations

import uuid

from pydantic import BaseModel, Field


class AppUserOut(BaseModel):
    id: uuid.UUID
    name: str | None = None
    email: str


class EmployeeCodeOut(BaseModel):
    id: uuid.UUID
    code: str
    display_name: str | None = None
    user_id: uuid.UUID | None = None
    user_name: str | None = None
    is_active: bool


class EmployeeMappingOut(BaseModel):
    id: uuid.UUID
    sheet_user_label: str
    user_id: uuid.UUID | None = None
    user_name: str | None = None
    employee_code_id: uuid.UUID | None = None
    backlink_count: int = 0
    is_active: bool = True
    # When set, this label is a spelling ALIAS rolled up into canonical_label.
    canonical_label: str | None = None


class EmployeeOverviewOut(BaseModel):
    codes: list[EmployeeCodeOut] = []
    mappings: list[EmployeeMappingOut] = []
    app_users: list[AppUserOut] = []


class EmployeeCodeCreate(BaseModel):
    code: str = Field(min_length=1, max_length=60)
    display_name: str | None = None
    user_id: uuid.UUID | None = None


class EmployeeCodeUpdate(BaseModel):
    display_name: str | None = None
    user_id: uuid.UUID | None = None
    is_active: bool | None = None


class EmployeeMappingUpdate(BaseModel):
    user_id: uuid.UUID | None = None
    employee_code_id: uuid.UUID | None = None
    # False = laid off: excluded from assignment pickers/planner/templates;
    # all historical work stays visible.
    is_active: bool | None = None


# ── Identity merge + fuzzy suggestions ────────────────────────────────────────
class MergeLabelsIn(BaseModel):
    canonical_label: str = Field(min_length=1, max_length=200)
    alias_labels: list[str] = Field(default_factory=list)
    # Optional app user to attribute the merged person to (null = leave as-is).
    user_id: uuid.UUID | None = None


class MergeResultOut(BaseModel):
    canonical_label: str
    alias_labels: list[str]
    rows_relabeled: int
    mappings_upserted: int


class SuggestedLabel(BaseModel):
    label: str
    backlink_count: int = 0


class LabelSuggestion(BaseModel):
    key: str
    canonical: str
    score: float
    members: list[SuggestedLabel] = []


class LabelSuggestionsOut(BaseModel):
    clusters: list[LabelSuggestion] = []
