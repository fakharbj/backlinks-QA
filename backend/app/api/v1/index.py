"""Index-check endpoints: trigger a check run and read the index summary."""

from __future__ import annotations

from fastapi import APIRouter, Depends

from app.core.config import settings
from app.core.deps import AuthContext, AuthCtx, DbSession, ReadSession, require
from app.core.errors import ValidationAppError
from app.core.rbac import Permission
from app.models.enums import AuditAction
from app.schemas.index_check import IndexCheckRequest, IndexCheckResponse, IndexSummaryOut
from app.services import audit_service, index_service

router = APIRouter(prefix="/index", tags=["index"])


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
