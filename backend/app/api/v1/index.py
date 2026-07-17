"""Index-check endpoints: trigger a check run and read the index summary."""

from __future__ import annotations

from fastapi import APIRouter, Depends

from app.core.config import settings
from app.core.deps import AuthContext, AuthCtx, DbSession, ReadSession, require
from app.core.errors import ValidationAppError
from app.core.rbac import Permission
from app.models.enums import AuditAction
from app.integrations import serper_pool
from app.schemas.index_check import IndexCheckRequest, IndexCheckResponse, IndexSummaryOut
from app.services import audit_service, index_service

router = APIRouter(prefix="/index", tags=["index"])


@router.get("/serper-status")
async def serper_status(
    ctx: AuthContext = Depends(require(Permission.RUN_CRAWLS)),
) -> dict:
    """Live view of the serper.dev key rotation pool — how many keys are configured,
    which one is active, which are exhausted, and approx credits used per key."""
    return await serper_pool.status()


@router.post("/serper-reset")
async def serper_reset(
    db: DbSession,
    ctx: AuthContext = Depends(require(Permission.RUN_CRAWLS)),
) -> dict:
    """Clear retired/usage state for the serper pool (use after topping up credits or
    swapping keys). All configured keys become eligible again."""
    count = await serper_pool.reset()
    await audit_service.record(
        db, action=AuditAction.RECHECK, actor_user_id=ctx.user.id, workspace_id=ctx.workspace_id,
        entity_type="index_check", entity_id=ctx.workspace_id, summary="Serper key pool reset",
    )
    await db.commit()
    return {"reset": True, "configured": count}


@router.get("/summary", response_model=IndexSummaryOut)
async def index_summary(
    ctx: AuthCtx, db: ReadSession, project_id=None
) -> IndexSummaryOut:
    counts = await index_service.summary(db, ctx.workspace_id, project_id)
    return IndexSummaryOut(
        indexed=counts.get("indexed", 0),
        not_indexed=counts.get("not_indexed", 0),
        uncertain=counts.get("uncertain", 0),
        unchecked=counts.get("unchecked", 0),
    )


@router.post("/check", response_model=IndexCheckResponse, status_code=202)
async def run_index_check(
    payload: IndexCheckRequest, db: DbSession,
    ctx: AuthContext = Depends(require(Permission.RUN_CRAWLS)),
) -> IndexCheckResponse:
    if not settings.INDEX_CHECK_ENABLED:
        raise ValidationAppError("Index checking is disabled (set INDEX_CHECK_ENABLED).")
    if payload.project_id is not None:
        ctx.assert_project(payload.project_id)
    await audit_service.record(
        db, action=AuditAction.RECHECK, actor_user_id=ctx.user.id, workspace_id=ctx.workspace_id,
        entity_type="index_check", entity_id=ctx.workspace_id, summary="Index check run",
    )
    await db.commit()

    from app.workers.tasks.index import dispatch_index_checks

    dispatch_index_checks.apply_async(
        args=[str(ctx.workspace_id), str(payload.project_id) if payload.project_id else None,
              payload.force],
        queue="index.check",
    )
    return IndexCheckResponse(
        message="Index check started — unique source URLs are being checked via the proxy."
    )


# ── Time-based index tracking settings (Setting KV "index_tracking") ─────────
from pydantic import BaseModel, Field  # noqa: E402


class IndexTrackingIn(BaseModel):
    enabled: bool = False
    # Days-after-creation checkpoints, e.g. [1, 7, 30] = re-check indexing one
    # day, one week and one month after each link is built.
    checkpoints: list[int] = Field(default_factory=lambda: [1, 7, 30], max_length=10)
    daily_cap: int = Field(default=300, ge=10, le=2000)


@router.get("/tracking")
async def get_index_tracking(ctx: AuthCtx, db: ReadSession) -> dict:
    """Current time-based tracking config (checkpoints in days + daily cap)."""
    from sqlalchemy import select as _select

    from app.models.settings import Setting
    from app.workers.tasks.index import TRACKING_DEFAULTS

    row = (
        await db.execute(
            _select(Setting).where(
                Setting.workspace_id == ctx.workspace_id, Setting.key == "index_tracking"
            )
        )
    ).scalar_one_or_none()
    cfg = dict(TRACKING_DEFAULTS)
    if row is not None and isinstance(row.value, dict):
        cfg.update({k: v for k, v in row.value.items() if k in TRACKING_DEFAULTS})
    return cfg


@router.put("/tracking")
async def put_index_tracking(
    payload: IndexTrackingIn, db: DbSession,
    ctx: AuthContext = Depends(require(Permission.MANAGE_WORKSPACE)),
) -> dict:
    """Save the tracking plan (admin, audited). The daily worker tick re-checks
    every link whose age crosses a checkpoint — serper quota always respected."""
    from sqlalchemy import select as _select

    from app.models.settings import Setting

    cps = sorted({int(c) for c in payload.checkpoints if 1 <= int(c) <= 365})
    if payload.enabled and not cps:
        raise ValidationAppError("Add at least one checkpoint (days), e.g. 1, 7, 30.")
    value = {"enabled": payload.enabled, "checkpoints": cps, "daily_cap": payload.daily_cap}
    row = (
        await db.execute(
            _select(Setting).where(
                Setting.workspace_id == ctx.workspace_id, Setting.key == "index_tracking"
            )
        )
    ).scalar_one_or_none()
    if row is None:
        db.add(Setting(workspace_id=ctx.workspace_id, key="index_tracking", value=value))
    else:
        row.value = value
    await audit_service.record(
        db, action=AuditAction.UPDATE, actor_user_id=ctx.user.id, workspace_id=ctx.workspace_id,
        entity_type="index_tracking", entity_id=ctx.workspace_id,
        summary=f"Index tracking {'ON' if payload.enabled else 'off'} · checkpoints {cps} · cap {payload.daily_cap}/day",
        after=value,
    )
    await db.commit()
    return value
