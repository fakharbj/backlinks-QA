"""Link-type catalog schemas (Phase 8)."""

from __future__ import annotations

import uuid

from pydantic import BaseModel, Field


class LinkTypeOut(BaseModel):
    id: uuid.UUID
    name: str
    slug: str
    color: str | None = None
    description: str | None = None
    is_active: bool
    backlink_count: int = 0


class LinkTypeCreate(BaseModel):
    name: str = Field(min_length=1, max_length=80)
    color: str | None = None
    description: str | None = None


class LinkTypeUpdate(BaseModel):
    name: str | None = Field(default=None, max_length=80)
    color: str | None = None
    description: str | None = None
    is_active: bool | None = None
