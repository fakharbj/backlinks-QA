"""Crawl job schemas."""

from __future__ import annotations

import uuid
from datetime import datetime

from app.models.enums import JobStatus, JobType
from app.schemas.common import ORMModel


class CrawlJobOut(ORMModel):
    id: uuid.UUID
    project_id: uuid.UUID | None
    job_type: JobType
    status: JobStatus
    total: int
    processed: int
    succeeded: int
    failed: int
    started_at: datetime | None
    finished_at: datetime | None
    created_at: datetime
    error: str | None
