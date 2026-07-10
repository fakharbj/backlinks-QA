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


class LinkTypeMergeIn(BaseModel):
    winner_id: uuid.UUID
    # Also rename the matching Google Sheet tabs (after the DB merge commits).
    rename_tabs: bool = True


class LinkTypeRenameIn(BaseModel):
    name: str = Field(min_length=1, max_length=60)  # backlink storage limit
    rename_tabs: bool = True
