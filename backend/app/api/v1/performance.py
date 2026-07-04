"""User performance endpoints (Phase 9 P1)."""

from __future__ import annotations

import uuid
from datetime import datetime

from fastapi import APIRouter, Query

from app.core.deps import AuthCtx, ReadSession
from app.services import performance_service

router = APIRouter(prefix="/performance", tags=["performance"])


@router.get("/user-dashboard")
async def user_dashboard(
    ctx: AuthCtx,
    db: ReadSession,
    user_label: str = Query(..., min_length=1, max_length=200),
    days: int = Query(30, ge=1, le=3660),
    date_from: datetime | None = Query(None),
    date_to: datetime | None = Query(None),
    project_id: uuid.UUID | None = Query(None),
    link_type: str | None = Query(None, max_length=80),
    compare: bool = Query(True),
) -> dict:
    """The admin's one-page view of a person: hours, plan completion, links,
    quality, per-project split, trends, rates and leave — scoped like every
    other people view (TeamLeads see their people; users see themselves)."""
    from app.services.workforce_service import visible_labels

    scope = await visible_labels(db, ctx)
    if scope is not None and user_label not in scope:
        from app.core.errors import NotFoundError

        raise NotFoundError("User not found")
    return await performance_service.user_dashboard(
        db, ctx, user_label=user_label, days=days, date_from=date_from, date_to=date_to,
        project_id=project_id, link_type=link_type, compare=compare,
    )


@router.get("/project-effort")
async def project_effort(
    ctx: AuthCtx,
    db: ReadSession,
    project_id: uuid.UUID = Query(...),
    days: int = Query(30, ge=1, le=3660),
    date_from: datetime | None = Query(None),
    date_to: datetime | None = Query(None),
    user_label: str | None = Query(None, max_length=200),
    link_type: str | None = Query(None, max_length=80),
) -> dict:
    """Project-effort rollup (hours/target/done/quality per person + trends)."""
    return await performance_service.project_effort(
        db, ctx, project_id=project_id, days=days, date_from=date_from, date_to=date_to,
        user_label=user_label, link_type=link_type,
    )


@router.get("/users")
async def user_performance(
    ctx: AuthCtx,
    db: ReadSession,
    days: int = Query(30, ge=1, le=3660),
    date_from: datetime | None = Query(None),
    date_to: datetime | None = Query(None),
    project_id: uuid.UUID | None = Query(None),
    compare: bool = Query(True),
    compare_from: datetime | None = Query(None),
    compare_to: datetime | None = Query(None),
) -> dict:
    return await performance_service.users(
        db, ctx, days=days, date_from=date_from, date_to=date_to,
        project_id=project_id, compare=compare,
        compare_from=compare_from, compare_to=compare_to,
    )
