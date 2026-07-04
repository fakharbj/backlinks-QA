"""Competitor analysis endpoints (Phase 8)."""

from __future__ import annotations

import uuid

from fastapi import APIRouter, Depends, Query

from app.core.deps import AuthContext, AuthCtx, DbSession, ReadSession, require
from app.core.rbac import Permission
from app.models.enums import AuditAction
from app.schemas.competitor import (
    CompetitorDecisionRequest,
    CompetitorDomainOut,
    CompetitorIngestRequest,
    CompetitorPreviewOut,
    CompetitorPreviewRequest,
    CompetitorSheetOut,
    CompetitorSummary,
)
from app.services import audit_service, competitor_service

router = APIRouter(prefix="/competitors", tags=["competitors"])

# SEMrush-style sample template so mapping "just works" on the first try.
_TEMPLATE_CSV = (
    "Source url,Anchor,Nofollow,Link type\r\n"
    "https://example-blog.com/best-tools-2026,best limo tools,FALSE,Article\r\n"
    "https://another-site.com/resources,resources page,TRUE,Business Listing\r\n"
    "https://writers-hub.com/guest-column,limo tips,FALSE,Guest Post\r\n"
)


@router.get("/template")
async def download_template() -> "PlainTextResponse":
    """Downloadable sample sheet for competitor backlink imports. Columns match a
    SEMrush backlink export ('Source url' is the only required column)."""
    from fastapi.responses import PlainTextResponse

    return PlainTextResponse(
        _TEMPLATE_CSV,
        media_type="text/csv",
        headers={"Content-Disposition": 'attachment; filename="competitor-backlinks-template.csv"'},
    )


@router.post("/preview", response_model=CompetitorPreviewOut)
async def preview(payload: CompetitorPreviewRequest, ctx: AuthCtx) -> CompetitorPreviewOut:
    """Show how pasted text will be read BEFORE importing: detected format,
    column mapping, row count and a sample — so mapping issues never block."""
    parsed = competitor_service.parse_competitor_text(payload.text)
    sample = [
        {"url": u, "anchor": a, "rel": r, "link_type": lt}
        for u, a, r, lt in parsed["rows"][:5]
    ]
    return CompetitorPreviewOut(
        format=parsed["format"], mapping=parsed["mapping"],
        row_count=len(parsed["rows"]), sample=sample, warnings=parsed["warnings"],
    )


@router.post("/ingest", response_model=CompetitorSheetOut, status_code=201)
async def ingest(
    payload: CompetitorIngestRequest, db: DbSession,
    ctx: AuthContext = Depends(require(Permission.IMPORT_BACKLINKS)),
) -> CompetitorSheetOut:
    sheet = await competitor_service.ingest(
        db, ctx, project_id=payload.project_id, competitor_url=payload.competitor_url,
        name=payload.name, raw_text=payload.text,
    )
    await audit_service.record(
        db, action=AuditAction.IMPORT, actor_user_id=ctx.user.id, workspace_id=ctx.workspace_id,
        entity_type="competitor_sheet", entity_id=sheet.id,
        summary=(
            f"Competitor upload '{sheet.name}' ({sheet.total_rows} links; "
            f"{sheet.new_domains} new domain(s), {sheet.existing_domains} already known)"
        ),
    )
    await db.commit()
    return CompetitorSheetOut.model_validate(sheet)


@router.get("/sheets", response_model=list[CompetitorSheetOut])
async def list_sheets(project_id: uuid.UUID, ctx: AuthCtx, db: ReadSession) -> list[CompetitorSheetOut]:
    rows = await competitor_service.list_sheets(db, ctx, project_id)
    return [CompetitorSheetOut.model_validate(r) for r in rows]


@router.delete("/sheets/{sheet_id}")
async def delete_sheet(
    sheet_id: uuid.UUID, db: DbSession,
    ctx: AuthContext = Depends(require(Permission.EDIT_BACKLINKS)),
) -> dict:
    name = await competitor_service.delete_sheet(db, ctx, sheet_id)
    await audit_service.record(
        db, action=AuditAction.DELETE, actor_user_id=ctx.user.id, workspace_id=ctx.workspace_id,
        entity_type="competitor_sheet", entity_id=sheet_id,
        summary=f"Deleted competitor upload '{name}'",
    )
    await db.commit()
    return {"message": f"Upload “{name}” deleted and opportunities recalculated"}


@router.get("/domains", response_model=list[CompetitorDomainOut])
async def list_domains(
    project_id: uuid.UUID,
    ctx: AuthCtx,
    db: ReadSession,
    category: str | None = Query(None),
    include_dismissed: bool = Query(True),
    exclude_guest_posts: bool = Query(False),
    search: str | None = Query(None),
    sort: str | None = Query(None, pattern="^(domain|links|ours|indexed|da|pa)$"),
    direction: str = Query("desc", pattern="^(asc|desc)$"),
    limit: int = Query(500, ge=1, le=2000),
    offset: int = Query(0, ge=0),
) -> list[CompetitorDomainOut]:
    rows = await competitor_service.list_domains(
        db, ctx, project_id, category=category,
        include_dismissed=include_dismissed, exclude_guest_posts=exclude_guest_posts,
        search=search, sort=sort, direction=direction, limit=limit, offset=offset,
    )
    return [CompetitorDomainOut(**r) for r in rows]


@router.get("/domain-backlinks")
async def domain_backlinks(
    project_id: uuid.UUID,
    domain: str,
    ctx: AuthCtx,
    db: ReadSession,
) -> list[dict]:
    """The competitor links behind one domain row (expand-in-place)."""
    return await competitor_service.domain_backlinks(db, ctx, project_id, domain)


@router.patch("/domains/decision", response_model=CompetitorSummary)
async def decide_domain(
    payload: CompetitorDecisionRequest, db: DbSession,
    ctx: AuthContext = Depends(require(Permission.EDIT_BACKLINKS)),
) -> CompetitorSummary:
    await competitor_service.decide(
        db, ctx, payload.project_id, payload.domain_key,
        status=payload.status, reason=payload.reason,
    )
    await audit_service.record(
        db, action=AuditAction.UPDATE, actor_user_id=ctx.user.id, workspace_id=ctx.workspace_id,
        entity_type="competitor_domain", entity_id=payload.project_id,
        summary=f"Opportunity {payload.domain_key} → {payload.status}",
    )
    await db.commit()
    return CompetitorSummary(**await competitor_service.summary(db, ctx, payload.project_id))


@router.get("/summary", response_model=CompetitorSummary)
async def summary(project_id: uuid.UUID, ctx: AuthCtx, db: ReadSession) -> CompetitorSummary:
    return CompetitorSummary(**await competitor_service.summary(db, ctx, project_id))


@router.post("/check-metrics")
async def check_metrics(
    project_id: uuid.UUID,
    db: DbSession,
    freshness_days: int = Query(10, ge=1, le=90),
    force: bool = Query(False),
    ctx: AuthContext = Depends(require(Permission.RUN_CRAWLS)),
) -> dict:
    """Fill DA/PA for competitor domains — reuse-first (our own recent checks
    cost nothing), respecting the freshness window unless forced."""
    result = await competitor_service.check_metrics(
        db, ctx, project_id, freshness_days=freshness_days, force=force
    )
    await db.commit()
    return result
