"""User performance endpoints (Phase 9 P1)."""

from __future__ import annotations

import uuid
from datetime import datetime

from fastapi import APIRouter, Query

from app.core.deps import AuthCtx, ReadSession
from app.services import performance_service

router = APIRouter(prefix="/performance", tags=["performance"])


@router.get("/users")
async def user_performance(
    ctx: AuthCtx,
    db: ReadSession,
    days: int = Query(30, ge=1, le=3660),
    date_from: datetime | None = Query(None),
    date_to: datetime | None = Query(None),
    project_id: uuid.UUID | None = Query(None),
    compare: bool = Query(True),
) -> dict:
    return await performance_service.users(
        db, ctx, days=days, date_from=date_from, date_to=date_to,
        project_id=project_id, compare=compare,
    )
