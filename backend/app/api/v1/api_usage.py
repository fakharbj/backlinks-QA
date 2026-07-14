"""External-API usage dashboard endpoints (Enterprise §3). Manager+."""

from __future__ import annotations

from fastapi import APIRouter, Depends, Query

from app.core.deps import AuthContext, require_role
from app.core.rbac import Role
from app.services import api_usage_service

router = APIRouter(prefix="/api-usage", tags=["api-usage"])


@router.get("")
async def api_usage_snapshot(
    ctx: AuthContext = Depends(require_role(Role.MANAGER)),
) -> dict:
    """Per-API health: limits, used today/this hour, success rate, avg response,
    last error/success — the "where did our quota go" answer."""
    return {
        "apis": await api_usage_service.snapshot(),
        "daily_limits": api_usage_service.daily_limits(),
        "hourly_limits": api_usage_service.hourly_limits(),
    }


@router.get("/series")
async def api_usage_series(
    api: str,
    granularity: str = Query("hour", pattern="^(hour|day)$"),
    periods: int = Query(48, ge=1, le=336),
    ctx: AuthContext = Depends(require_role(Role.MANAGER)),
) -> dict:
    """Chart series for one API (hourly ≤14 days, daily ≤35 days)."""
    if api.lower() not in api_usage_service.KNOWN_APIS:
        return {"api": api, "points": []}
    return {
        "api": api.lower(),
        "granularity": granularity,
        "points": await api_usage_service.series(api, granularity=granularity, periods=periods),
    }
