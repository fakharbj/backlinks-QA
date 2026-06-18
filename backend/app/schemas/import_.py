"""Import schemas."""

from __future__ import annotations

import uuid
from datetime import datetime

from pydantic import BaseModel, Field

from app.models.enums import ImportSource, ImportStatus
from app.schemas.common import ORMModel


class ImportPreview(BaseModel):
    headers: list[str]
    suggested_mapping: dict[str, str]
    sample_rows: list[dict[str, str]]
    row_count: int


class PastePreviewRequest(BaseModel):
    text: str


class PasteImportRequest(BaseModel):
    project_id: uuid.UUID
    text: str
    column_mapping: dict[str, str] | None = None


class ImportOut(ORMModel):
    id: uuid.UUID
    project_id: uuid.UUID
    source: ImportSource
    filename: str | None
    status: ImportStatus
    total_rows: int
    processed_rows: int
    imported_rows: int
    duplicate_rows: int
    error_rows: int
    error: str | None
    created_at: datetime


class ImportRowError(BaseModel):
    row_number: int
    error: str | None
    raw: dict
