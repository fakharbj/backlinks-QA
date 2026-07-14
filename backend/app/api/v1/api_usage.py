"""External-API usage dashboard endpoints (Enterprise §3). Manager+ reads;
limit configuration is Admin-only (it controls real spend)."""

from __future__ import annotations

from fastapi import APIRouter, Depends, Query
from pydantic import BaseModel, Field

from app.core.deps import AuthContext, DbSession, require_role
from app.core.rbac import Role
from app.models.enums import AuditAction
from app.services import api_usage_service, audit_service

router = APIRouter(prefix="/api-usage", tags=["api-usage"])


class ApiLimitsIn(BaseModel):
    # api-name → max requests; 0/absent = no limit for that API.
    daily: dict[str, int] = Field(default_factory=dict)
    hourly: dict[str, int] = Field(default_factory=dict)


@router.get("")
async def api_usage_snapshot(
    ctx: AuthContext = Depends(require_role(Role.MANAGER)),
) -> dict:
    """Per-API health: limits, used today/this hour, success rate, avg response,
    last error/success — the "where did our quota go" answer."""
    daily, hourly = await api_usage_service.effective_limits()
    return {
        "apis": await api_usage_service.snapshot(),
        "daily_limits": daily,
        "hourly_limits": hourly,
        "known_apis": list(api_usage_service.KNOWN_APIS),
    }


@router.put("/limits")
async def put_api_limits(
    payload: ApiLimitsIn, db: DbSession,
    ctx: AuthContext = Depends(require_role(Role.ADMIN)),
) -> dict:
    """Set the daily/hourly request limits per API — in-app, no server access
    needed. When a limit is reached, dependent QA parks as "Waiting for API"
    instead of burning failed requests. Audited."""
    await api_usage_service.store_limits(db, ctx.workspace_id, payload.daily, payload.hourly)
    await audit_service.record(
        db, action=AuditAction.UPDATE, actor_user_id=ctx.user.id, workspace_id=ctx.workspace_id,
        entity_type="api_limits", entity_id=ctx.workspace_id,
        summary="API request limits updated",
        after={"daily": payload.daily, "hourly": payload.hourly},
    )
    await db.commit()
    daily, hourly = await api_usage_service.effective_limits()
    return {"daily_limits": daily, "hourly_limits": hourly}


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
