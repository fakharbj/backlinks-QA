"""Competitor analysis endpoints (Phase 8)."""

from __future__ import annotations

import uuid

from fastapi import APIRouter, Depends, Query

from app.core.deps import AuthContext, AuthCtx, DbSession, ReadSession, require
from app.core.rbac import Permission
from app.models.enums import AuditAction
from app.schemas.competitor import (
    CompetitorDomainOut,
    CompetitorIngestRequest,
    CompetitorSheetOut,
    CompetitorSummary,
)
from app.services import audit_service, competitor_service

router = APIRouter(prefix="/competitors", tags=["competitors"])


@router.post("/ingest", response_model=CompetitorSheetOut, status_code=201)
async def ingest(
    payload: CompetitorIngestRequest, db: DbSession,
    ctx: AuthContext = Depends(require(Permission.IMPORT_BACKLINKS)),
) -> CompetitorSheetOut:
    sheet = await competitor_service.ingest(
        db, ctx, project_id=payload.project_id, name=payload.name, raw_text=payload.text
    )
    await audit_service.record(
        db, action=AuditAction.IMPORT, actor_user_id=ctx.user.id, workspace_id=ctx.workspace_id,
        entity_type="competitor_sheet", entity_id=sheet.id,
        summary=f"Competitor upload '{sheet.name}' ({sheet.total_rows} links, {sheet.new_domains} new domains)",
    )
    await db.commit()
    return CompetitorSheetOut.model_validate(sheet)


@router.get("/sheets", response_model=list[CompetitorSheetOut])
async def list_sheets(project_id: uuid.UUID, ctx: AuthCtx, db: ReadSession) -> list[CompetitorSheetOut]:
    rows = await competitor_service.list_sheets(db, ctx, project_id)
    return [CompetitorSheetOut.model_validate(r) for r in rows]


@router.get("/domains", response_model=list[CompetitorDomainOut])
async def list_domains(
    project_id: uuid.UUID, ctx: AuthCtx, db: ReadSession, category: str | None = Query(None)
) -> list[CompetitorDomainOut]:
    rows = await competitor_service.list_domains(db, ctx, project_id, category=category)
    return [CompetitorDomainOut.model_validate(r) for r in rows]


@router.get("/summary", response_model=CompetitorSummary)
async def summary(project_id: uuid.UUID, ctx: AuthCtx, db: ReadSession) -> CompetitorSummary:
    return CompetitorSummary(**await competitor_service.summary(db, ctx, project_id))
