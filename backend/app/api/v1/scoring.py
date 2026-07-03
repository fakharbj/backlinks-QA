"""Dynamic scoring configuration endpoints (Phase 8 F17–19).

Reads are open to any member; writes (save a new rule-set version, re-score) need
MANAGE_WORKSPACE — scoring rules are a workspace governance setting. Every config
write creates an immutable new version; re-score recomputes existing verdicts from
their frozen issue snapshots (no re-crawl).
"""

from __future__ import annotations

import uuid

from fastapi import APIRouter, Depends, Query

from app.core.deps import AuthContext, AuthCtx, DbSession, ReadSession, require
from app.core.rbac import Permission
from app.models.enums import AuditAction
from app.schemas.scoring import (
    RescoreRequest,
    RescoreResult,
    ScoringConfigOut,
    ScoringConfigSave,
    ScoringParameterOut,
    ScoringVersionOut,
)
from app.services import audit_service, rescore_service, scoring_config_service

router = APIRouter(prefix="/scoring", tags=["scoring"])


def _param_out(p) -> ScoringParameterOut:
    return ScoringParameterOut(
        key=p.key, display_name=p.display_name, description=p.description,
        category=p.category, value_kind=p.value_kind, outcomes=p.outcomes,
        default_points=p.default_points, sort_order=p.sort_order,
    )


async def _config_out(
    db, ctx, scope: str, scope_ref_id: uuid.UUID | None,
    link_type_id: uuid.UUID | None = None,
) -> ScoringConfigOut:
    cfg = await scoring_config_service.effective_config(
        db, workspace_id=ctx.workspace_id, scope=scope, scope_ref_id=scope_ref_id,
        link_type_id=link_type_id,
    )
    params = await scoring_config_service.list_parameters(db)
    return ScoringConfigOut(parameters=[_param_out(p) for p in params], **cfg)


@router.get("/parameters", response_model=list[ScoringParameterOut])
async def list_parameters(ctx: AuthCtx, db: ReadSession) -> list[ScoringParameterOut]:
    return [_param_out(p) for p in await scoring_config_service.list_parameters(db)]


@router.get("/config", response_model=ScoringConfigOut)
async def get_config(
    ctx: AuthCtx,
    db: ReadSession,
    scope: str = Query("global"),
    scope_ref_id: uuid.UUID | None = Query(None),
    link_type_id: uuid.UUID | None = Query(None),
) -> ScoringConfigOut:
    return await _config_out(db, ctx, scope, scope_ref_id, link_type_id)


@router.put("/config", response_model=ScoringConfigOut)
async def save_config(
    payload: ScoringConfigSave, db: DbSession,
    ctx: AuthContext = Depends(require(Permission.MANAGE_WORKSPACE)),
) -> ScoringConfigOut:
    row = await scoring_config_service.save_version(
        db, workspace_id=ctx.workspace_id, scope=payload.scope, scope_ref_id=payload.scope_ref_id,
        link_type_id=payload.link_type_id,
        rules=payload.rules, bands=payload.bands, note=payload.note, created_by=ctx.user.id,
    )
    await audit_service.record(
        db, action=AuditAction.UPDATE, actor_user_id=ctx.user.id, workspace_id=ctx.workspace_id,
        entity_type="scoring_rule_version", entity_id=row.id,
        summary=f"Saved {payload.scope} scoring v{row.version}",
    )
    await db.commit()
    return await _config_out(db, ctx, payload.scope, payload.scope_ref_id, payload.link_type_id)


@router.get("/versions", response_model=list[ScoringVersionOut])
async def list_versions(
    ctx: AuthCtx, db: ReadSession,
    scope: str = Query("global"), scope_ref_id: uuid.UUID | None = Query(None),
    link_type_id: uuid.UUID | None = Query(None),
) -> list[ScoringVersionOut]:
    rows = await scoring_config_service.list_versions(
        db, workspace_id=ctx.workspace_id, scope=scope, scope_ref_id=scope_ref_id,
        link_type_id=link_type_id,
    )
    return [
        ScoringVersionOut(
            id=r.id, scope=r.scope, scope_ref_id=r.scope_ref_id, version=r.version,
            is_latest=r.is_latest, note=r.note, created_at=r.created_at,
        )
        for r in rows
    ]


@router.post("/rescore", response_model=RescoreResult)
async def rescore(
    payload: RescoreRequest, db: DbSession,
    ctx: AuthContext = Depends(require(Permission.MANAGE_WORKSPACE)),
) -> RescoreResult:
    from app.services import batch_service

    batch_id = None
    if not payload.preview:
        batch_id = await batch_service.start(
            "rescore", ctx.workspace_id,
            project_id=payload.scope_ref_id if payload.scope == "project" else None,
            label=f"Re-score ({payload.scope})", started_by=ctx.user.id,
        )
    try:
        result = await rescore_service.rescore(
            db, workspace_id=ctx.workspace_id, scope=payload.scope,
            scope_ref_id=payload.scope_ref_id, preview=payload.preview,
            link_type_id=payload.link_type_id,
        )
    except Exception as exc:  # noqa: BLE001 — close the batch, then surface the error
        await batch_service.finish(batch_id, status="failed", error=str(exc)[:500])
        raise
    if not payload.preview:
        await audit_service.record(
            db, action=AuditAction.UPDATE, actor_user_id=ctx.user.id,
            workspace_id=ctx.workspace_id, entity_type="scoring_rescore",
            entity_id=payload.scope_ref_id or ctx.workspace_id,
            summary=f"Re-scored {result['changed']}/{result['total']} ({payload.scope})",
        )
        await db.commit()
        await batch_service.update(
            batch_id,
            totals={"total": result["total"], "done": result["total"], "ok": result["changed"]},
        )
        await batch_service.add_log(
            batch_id,
            f"{result['changed']} of {result['total']} links changed "
            f"(average {result['avg_score_delta']:+} points).",
        )
        await batch_service.finish(batch_id)
    return RescoreResult(**result)
