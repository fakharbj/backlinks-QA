"""Crawl-job status endpoints."""

from __future__ import annotations

import uuid

from fastapi import APIRouter

from app.core.deps import AuthCtx, ReadSession
from app.schemas.crawl import CrawlJobOut
from app.services import crawl_service

router = APIRouter(prefix="/crawl-jobs", tags=["crawl"])


@router.get("/{job_id}", response_model=CrawlJobOut)
async def get_job(job_id: uuid.UUID, ctx: AuthCtx, db: ReadSession) -> CrawlJobOut:
    job = await crawl_service.get_job(db, ctx, job_id)
    return CrawlJobOut.model_validate(job)
