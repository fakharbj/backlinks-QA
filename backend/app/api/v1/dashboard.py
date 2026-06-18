"""Dashboard endpoint."""

from __future__ import annotations

import uuid

from fastapi import APIRouter

from app.core.deps import AuthCtx, ReadSession
from app.schemas.dashboard import DashboardResponse
from app.services import dashboard_service

router = APIRouter(prefix="/dashboard", tags=["dashboard"])


@router.get("", response_model=DashboardResponse)
async def dashboard(
    ctx: AuthCtx, db: ReadSession, project_id: uuid.UUID | None = None
) -> DashboardResponse:
    return await dashboard_service.build_dashboard(db, ctx, project_id)
