"""Source main-domain analytics endpoints (Phase 8, features 11/12).

List + detail read the stored aggregates (fast); recompute refreshes them.
"""

from __future__ import annotations

import uuid

from fastapi import APIRouter, Depends, status
from pydantic import BaseModel, Field

from app.core.deps import AuthContext, AuthCtx, DbSession, ReadSession, require
from app.core.rbac import Permission
from app.models.enums import AuditAction
from app.schemas.source_domain import SourceDomainDetailOut, SourceDomainOut
from app.services import audit_service, batch_review_service
from app.services import source_domain_service as svc

router = APIRouter(prefix="/source-domains", tags=["source-domains"])


@router.get("", response_model=list[SourceDomainOut])
async def list_source_domains(
    ctx: AuthCtx, db: ReadSession,
    sort: str = "backlinks", order: str = "desc", search: str | None = None, limit: int = 200,
) -> list[SourceDomainOut]:
    rows = await svc.list_domains(db, ctx, sort=sort, order=order, search=search, limit=limit)
    return [SourceDomainOut(**r) for r in rows]


class DomainImportRequest(BaseModel):
    text: str = Field(min_length=1, max_length=2_000_000)
    label: str | None = Field(default=None, max_length=200)


# NOTE: declared before /{domain_id} so the literal path wins route matching.
@router.post("/import", status_code=status.HTTP_202_ACCEPTED)
async def import_source_domains(
    payload: DomainImportRequest, db: DbSession,
    ctx: AuthContext = Depends(require(Permission.IMPORT_BACKLINKS)),
) -> dict:
    """Stage a pasted list of domains/URLs into a review batch (0029). Each
    domain is reviewable (check DA/PA/Spam/AS/age) and joins the Source Domains
    catalog only when approved in the Batches desk."""
    batch = await batch_review_service.stage_domain_import(
        db, ctx, text_block=payload.text, label=payload.label
    )
    await audit_service.record(
        db, action=AuditAction.IMPORT, actor_user_id=ctx.user.id, workspace_id=ctx.workspace_id,
        entity_type="batch", entity_id=batch.id,
        summary=f"Staged domain import for review (#B-{batch.seq})",
    )
    await db.commit()
    c = batch.counters or {}
    return {
        "batch_id": str(batch.id),
        "seq": batch.seq,
        "total": int((batch.totals or {}).get("total", 0)),
        "new": int(c.get("new", 0)),
        "existing": int(c.get("existing", 0)),
        "duplicate": int(c.get("duplicate", 0)),
        "message": f"Review batch #B-{batch.seq} created — approve domains to add them to the catalog",
    }


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
    db: DbSession, force: bool = False, providers: str | None = None,
    ctx: AuthContext = Depends(require(Permission.RUN_CRAWLS)),
) -> list[SourceDomainOut]:
    """Fetch metrics for stale domains (batch-capped per call): DA/PA via Moz,
    AS via Semrush. ``providers`` is a comma list (``moz,semrush``) scoping the
    fetch; omit for all providers."""
    wanted = {p.strip() for p in (providers or "").split(",") if p.strip() in ("moz", "semrush")}
    await svc.fetch_metrics(db, ctx, force=force, providers=wanted or None)
    await db.commit()
    rows = await svc.list_domains(db, ctx)
    return [SourceDomainOut(**r) for r in rows]
