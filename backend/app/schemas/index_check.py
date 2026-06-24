"""Index-check schemas (Phase 4)."""

from __future__ import annotations

import uuid

from pydantic import BaseModel


class IndexCheckRequest(BaseModel):
    project_id: uuid.UUID | None = None
    force: bool = False  # re-check even if within the re-check window


class IndexCheckResponse(BaseModel):
    message: str


class IndexSummaryOut(BaseModel):
    indexed: int = 0
    not_indexed: int = 0
    uncertain: int = 0
    unchecked: int = 0
