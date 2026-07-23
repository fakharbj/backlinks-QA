"""Dashboard endpoint."""

from __future__ import annotations

import uuid

from fastapi import APIRouter, Query

from app.core.deps import AuthCtx, ReadSession
from app.schemas.dashboard import DashboardResponse
from app.services import dashboard_service

router = APIRouter(prefix="/dashboard", tags=["dashboard"])


@router.get("", response_model=DashboardResponse)
async def dashboard(
    ctx: AuthCtx, db: ReadSession, project_id: uuid.UUID | None = None,
    project_status: str = Query(default="all", pattern="^(all|active|inactive)$"),
) -> DashboardResponse:
    return await dashboard_service.build_dashboard(db, ctx, project_id, project_status=project_status)


@router.get("/trends")
async def dashboard_trends(
    ctx: AuthCtx, db: ReadSession, days: int = 30,
    granularity: str = Query(default="week", pattern="^(day|week|month)$"),
    project_id: uuid.UUID | None = None,
    project_status: str = Query(default="all", pattern="^(all|active|inactive)$"),
) -> dict:
    return await dashboard_service.trends(
        db, ctx, days=days, granularity=granularity, project_id=project_id,
        project_status=project_status,
    )
