"""Project settings + main domain schemas (Phase 8, feature 2)."""

from __future__ import annotations

import uuid

from pydantic import BaseModel, Field


class ProjectDomainOut(BaseModel):
    id: uuid.UUID
    domain: str
    is_primary: bool


class ProjectSettingsOut(BaseModel):
    project_id: uuid.UUID
    scoring_profile: str
    index_expected: bool
    treat_sponsored_as_follow: bool
    status_thresholds: dict = {}
    domains: list[ProjectDomainOut] = []


class ProjectSettingsUpdate(BaseModel):
    scoring_profile: str | None = None
    index_expected: bool | None = None
    treat_sponsored_as_follow: bool | None = None
    status_thresholds: dict | None = None


class ProjectDomainCreate(BaseModel):
    domain: str = Field(min_length=1, max_length=255)
