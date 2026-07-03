"""Batch history endpoints (Phase 9) — the operations layer over every run."""

from __future__ import annotations

import uuid

from fastapi import APIRouter, Depends, Query
from pydantic import BaseModel

from app.core.deps import AuthContext, AuthCtx, DbSession, ReadSession, require
from app.core.errors import NotFoundError
from app.core.rbac import Permission
from app.models.batch import Batch, BatchLog
from app.services import batch_service

router = APIRouter(prefix="/batches", tags=["batches"])


class BatchOut(BaseModel):
    id: uuid.UUID
    kind: str
    status: str
    label: str | None
    project_id: uuid.UUID | None
    started_by: uuid.UUID | None
    totals: dict
    counters: dict
    meta: dict
    error: str | None
    started_at: str
    finished_at: str | None


class BatchLogOut(BaseModel):
    level: str
    message: str
    row_ref: str | None
    data: dict
    created_at: str


def _out(b: Batch) -> BatchOut:
    return BatchOut(
        id=b.id, kind=b.kind, status=b.status, label=b.label, project_id=b.project_id,
        started_by=b.started_by, totals=b.totals or {}, counters=b.counters or {},
        meta=b.meta or {}, error=b.error,
        started_at=b.started_at.isoformat(),
        finished_at=b.finished_at.isoformat() if b.finished_at else None,
    )


@router.get("", response_model=list[BatchOut])
async def list_batches(
    ctx: AuthCtx,
    db: ReadSession,
    kind: str | None = Query(None),
    status: str | None = Query(None),
    project_id: uuid.UUID | None = Query(None),
    limit: int = Query(100),
) -> list[BatchOut]:
    if project_id is not None:
        ctx.assert_project(project_id)
    rows = await batch_service.list_batches(
        db, ctx.workspace_id, kind=kind, status=status, project_id=project_id, limit=limit
    )
    return [_out(b) for b in rows]


@router.get("/{batch_id}", response_model=BatchOut)
async def get_batch(batch_id: uuid.UUID, ctx: AuthCtx, db: ReadSession) -> BatchOut:
    b = await db.get(Batch, batch_id)
    if b is None or b.workspace_id != ctx.workspace_id:
        raise NotFoundError("Batch not found")
    return _out(b)


@router.delete("/{batch_id}")
async def delete_batch(
    batch_id: uuid.UUID, db: DbSession,
    ctx: AuthContext = Depends(require(Permission.MANAGE_WORKSPACE)),
) -> dict:
    """Remove one run from history (admin housekeeping; its logs go with it)."""
    from sqlalchemy import delete as sa_delete

    b = await db.get(Batch, batch_id)
    if b is None or b.workspace_id != ctx.workspace_id:
        raise NotFoundError("Batch not found")
    await db.execute(sa_delete(BatchLog).where(BatchLog.batch_id == batch_id))
    await db.delete(b)
    await db.commit()
    return {"message": "Run removed from history"}


@router.get("/{batch_id}/logs", response_model=list[BatchLogOut])
async def get_batch_logs(batch_id: uuid.UUID, ctx: AuthCtx, db: ReadSession) -> list[BatchLogOut]:
    b = await db.get(Batch, batch_id)
    if b is None or b.workspace_id != ctx.workspace_id:
        raise NotFoundError("Batch not found")
    logs = await batch_service.get_logs(db, batch_id)
    return [
        BatchLogOut(
            level=r.level, message=r.message, row_ref=r.row_ref, data=r.data or {},
            created_at=r.created_at.isoformat(),
        )
        for r in logs
    ]
