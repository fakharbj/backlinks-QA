"""Source main-domain analytics endpoints (Phase 8, features 11/12).

List + detail read the stored aggregates (fast); recompute refreshes them.
"""

from __future__ import annotations

import uuid

from fastapi import APIRouter, Depends

from app.core.deps import AuthContext, AuthCtx, DbSession, ReadSession, require
from app.core.rbac import Permission
from app.schemas.source_domain import SourceDomainDetailOut, SourceDomainOut
from app.services import source_domain_service as svc

router = APIRouter(prefix="/source-domains", tags=["source-domains"])


@router.get("", response_model=list[SourceDomainOut])
async def list_source_domains(
    ctx: AuthCtx, db: ReadSession,
    sort: str = "backlinks", order: str = "desc", search: str | None = None, limit: int = 200,
) -> list[SourceDomainOut]:
    rows = await svc.list_domains(db, ctx, sort=sort, order=order, search=search, limit=limit)
    return [SourceDomainOut(**r) for r in rows]


@router.get("/{domain_id}", response_model=SourceDomainDetailOut)
async def source_domain_detail(
    domain_id: uuid.UUID, ctx: AuthCtx, db: ReadSession
) -> SourceDomainDetailOut:
    return SourceDomainDetailOut(**await svc.detail(db, ctx, domain_id))


@router.post("/recompute", response_model=list[SourceDomainOut])
async def recompute_source_domains(
    db: DbSession, ctx: AuthContext = Depends(require(Permission.RUN_CRAWLS))
) -> list[SourceDomainOut]:
    await svc.recompute(db, ctx.workspace_id)
    await db.commit()
    rows = await svc.list_domains(db, ctx)
    return [SourceDomainOut(**r) for r in rows]
