"""Report schemas."""

from __future__ import annotations

import uuid
from datetime import datetime

from pydantic import BaseModel, Field

from app.models.enums import ReportFormat, ReportStatus, ReportType
from app.schemas.common import ORMModel


class ReportCreate(BaseModel):
    report_type: ReportType
    format: ReportFormat = ReportFormat.PDF
    title: str = Field(min_length=1, max_length=300)
    project_id: uuid.UUID | None = None
    filters: dict = Field(default_factory=dict)


class ReportOut(ORMModel):
    id: uuid.UUID
    project_id: uuid.UUID | None
    report_type: ReportType
    format: ReportFormat
    status: ReportStatus
    title: str
    row_count: int | None
    file_size: int | None
    error: str | None
    created_at: datetime
    completed_at: datetime | None


class ReportDownload(BaseModel):
    url: str
    expires_in: int
