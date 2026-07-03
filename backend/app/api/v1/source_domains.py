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


# NOTE: declared before /{domain_id} so the literal path wins route matching.
@router.get("/project-view")
async def project_view(
    project_id: uuid.UUID, ctx: AuthCtx, db: ReadSession, limit: int = 500
) -> dict:
    """Domains used by this project vs domains known globally but not used here."""
    return await svc.project_view(db, ctx, project_id, limit=min(max(limit, 1), 1000))


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


@router.post("/fetch-metrics", response_model=list[SourceDomainOut])
async def fetch_source_domain_metrics(
    db: DbSession, force: bool = False,
    ctx: AuthContext = Depends(require(Permission.RUN_CRAWLS)),
) -> list[SourceDomainOut]:
    """Fetch Moz/Semrush/domain-age for stale domains (batch-capped per call)."""
    await svc.fetch_metrics(db, ctx, force=force)
    await db.commit()
    rows = await svc.list_domains(db, ctx)
    return [SourceDomainOut(**r) for r in rows]
