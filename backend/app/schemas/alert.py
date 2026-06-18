"""Alert-rule and notification schemas."""

from __future__ import annotations

import uuid
from datetime import datetime

from pydantic import BaseModel, Field

from app.schemas.common import ORMModel


class AlertRuleCreate(BaseModel):
    name: str = Field(min_length=1, max_length=200)
    project_id: uuid.UUID | None = None
    event_types: list[str] = Field(default_factory=list)  # empty == all
    min_severity: str = "HIGH"
    score_drop_threshold: int | None = None
    channels: list[str] = Field(default_factory=lambda: ["in_app"])
    channel_config: dict = Field(default_factory=dict)
    dedup_window_minutes: int = 60
    quiet_hours: dict = Field(default_factory=dict)
    digest_mode: bool = False
    is_active: bool = True


class AlertRuleUpdate(BaseModel):
    name: str | None = None
    event_types: list[str] | None = None
    min_severity: str | None = None
    score_drop_threshold: int | None = None
    channels: list[str] | None = None
    channel_config: dict | None = None
    dedup_window_minutes: int | None = None
    quiet_hours: dict | None = None
    digest_mode: bool | None = None
    is_active: bool | None = None


class AlertRuleOut(ORMModel):
    id: uuid.UUID
    name: str
    project_id: uuid.UUID | None
    event_types: list[str]
    min_severity: str
    score_drop_threshold: int | None
    channels: list[str]
    dedup_window_minutes: int
    digest_mode: bool
    is_active: bool


class NotificationOut(ORMModel):
    id: uuid.UUID
    project_id: uuid.UUID | None
    backlink_id: uuid.UUID | None
    channel: str
    status: str
    severity: str | None
    title: str
    body: str | None
    created_at: datetime
    read_at: datetime | None
