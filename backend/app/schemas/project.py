"""Project / vendor / campaign schemas."""

from __future__ import annotations

import uuid
from datetime import datetime

from pydantic import BaseModel, Field

from app.models.enums import ProjectStatus, ScheduleInterval
from app.schemas.common import ORMModel


class ProjectCreate(BaseModel):
    name: str = Field(min_length=1, max_length=200)
    client_name: str | None = None
    target_domain: str | None = None
    target_urls: list[str] = Field(default_factory=list)
    campaign: str | None = None
    notes: str | None = None
    tags: list[str] = Field(default_factory=list)
    schedule_interval: ScheduleInterval = ScheduleInterval.DAILY
    treat_sponsored_as_follow: bool = True


class ProjectUpdate(BaseModel):
    name: str | None = Field(default=None, max_length=200)
    client_name: str | None = None
    target_domain: str | None = None
    target_urls: list[str] | None = None
    campaign: str | None = None
    notes: str | None = None
    tags: list[str] | None = None
    status: ProjectStatus | None = None
    schedule_interval: ScheduleInterval | None = None
    treat_sponsored_as_follow: bool | None = None


class ProjectOut(ORMModel):
    id: uuid.UUID
    name: str
    slug: str
    client_name: str | None
    target_domain: str | None
    target_urls: list[str]
    campaign: str | None
    notes: str | None
    tags: list[str]
    status: ProjectStatus
    schedule_interval: ScheduleInterval
    treat_sponsored_as_follow: bool
    last_checked_at: datetime | None
    created_at: datetime


class VendorCreate(BaseModel):
    name: str = Field(min_length=1, max_length=200)
    contact_email: str | None = None
    website: str | None = None
    notes: str | None = None


class VendorOut(ORMModel):
    id: uuid.UUID
    name: str
    contact_email: str | None
    website: str | None
    notes: str | None


class CampaignCreate(BaseModel):
    project_id: uuid.UUID
    name: str = Field(min_length=1, max_length=200)
    campaign_type: str = "editorial"
    budget: float | None = None
    notes: str | None = None


class CampaignOut(ORMModel):
    id: uuid.UUID
    project_id: uuid.UUID
    name: str
    campaign_type: str
    budget: float | None
    notes: str | None


class ProjectMemberAdd(BaseModel):
    user_id: uuid.UUID
    role: str | None = None
