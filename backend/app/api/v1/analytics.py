"""Dynamic analytics endpoint (Phase 5)."""

from __future__ import annotations

from fastapi import APIRouter

from app.core.deps import AuthCtx, ReadSession
from app.schemas.analytics import AnalyticsRequest, AnalyticsResponse
from app.services import analytics_service

router = APIRouter(prefix="/analytics", tags=["analytics"])


@router.post("/query", response_model=AnalyticsResponse)
async def analytics_query(
    payload: AnalyticsRequest, ctx: AuthCtx, db: ReadSession
) -> AnalyticsResponse:
    filters = payload.filters or {}
    summary = await analytics_service.summary(db, ctx, filters)
    facets = (
        await analytics_service.facets(db, ctx, filters, payload.facets)
        if payload.facets else {}
    )
    groups = (
        await analytics_service.groups(db, ctx, filters, payload.group_by)
        if payload.group_by else []
    )
    return AnalyticsResponse(
        summary=summary, facets=facets, groups=groups,
        dimensions=analytics_service.allowed_dimensions(),
    )
