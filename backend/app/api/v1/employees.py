"""Employee code + sheet-user mapping endpoints (Phase 8, feature 3).

Read for any member; mutations require Manager+ (people/identity management).
"""

from __future__ import annotations

import uuid

from fastapi import APIRouter, Depends

from app.core.deps import AuthContext, AuthCtx, DbSession, ReadSession, require_role
from app.core.rbac import Role
from app.models.enums import AuditAction
from app.schemas.employee import (
    EmployeeCodeCreate,
    EmployeeCodeOut,
    EmployeeCodeUpdate,
    EmployeeMappingOut,
    EmployeeMappingUpdate,
    EmployeeOverviewOut,
    LabelSuggestionsOut,
    MergeLabelsIn,
    MergeResultOut,
)
from app.services import audit_service
from app.services import employee_service as svc

router = APIRouter(prefix="/employees", tags=["employees"])


@router.get("", response_model=EmployeeOverviewOut)
async def overview(
    db: ReadSession, ctx: AuthContext = Depends(require_role(Role.MANAGER))
) -> EmployeeOverviewOut:
    """People/identity catalog is management-only (emails + team-wide mapping)."""
    return EmployeeOverviewOut(**await svc.overview(db, ctx))


@router.post("/sync", response_model=EmployeeOverviewOut)
async def sync(db: DbSession, ctx: AuthContext = Depends(require_role(Role.MANAGER))) -> EmployeeOverviewOut:
    result = await svc.sync_from_data(db, ctx)
    await audit_service.record(
        db, action=AuditAction.UPDATE, actor_user_id=ctx.user.id, workspace_id=ctx.workspace_id,
        entity_type="employee", entity_id=ctx.workspace_id,
        summary=f"Synced employees ({result['new_codes']} codes, {result['new_mappings']} users)",
    )
    await db.commit()
    return EmployeeOverviewOut(**await svc.overview(db, ctx))


@router.post("/codes", response_model=EmployeeCodeOut, status_code=201)
async def create_code(
    payload: EmployeeCodeCreate, db: DbSession,
    ctx: AuthContext = Depends(require_role(Role.MANAGER)),
) -> EmployeeCodeOut:
    ec = await svc.create_code(db, ctx, payload)
    await audit_service.record(
        db, action=AuditAction.CREATE, actor_user_id=ctx.user.id, workspace_id=ctx.workspace_id,
        entity_type="employee_code", entity_id=ec.id, summary=f"Created employee code {ec.code}",
    )
    await db.commit()
    return EmployeeCodeOut(
        id=ec.id, code=ec.code, display_name=ec.display_name, user_id=ec.user_id,
        is_active=ec.is_active,
    )


@router.patch("/codes/{code_id}", response_model=EmployeeCodeOut)
async def update_code(
    code_id: uuid.UUID, payload: EmployeeCodeUpdate, db: DbSession,
    ctx: AuthContext = Depends(require_role(Role.MANAGER)),
) -> EmployeeCodeOut:
    ec = await svc.update_code(db, ctx, code_id, payload)
    await audit_service.record(
        db, action=AuditAction.UPDATE, actor_user_id=ctx.user.id, workspace_id=ctx.workspace_id,
        entity_type="employee_code", entity_id=ec.id, summary=f"Updated employee code {ec.code}",
    )
    await db.commit()
    return EmployeeCodeOut(
        id=ec.id, code=ec.code, display_name=ec.display_name, user_id=ec.user_id,
        is_active=ec.is_active,
    )


@router.delete("/codes/{code_id}")
async def delete_code(
    code_id: uuid.UUID, db: DbSession,
    ctx: AuthContext = Depends(require_role(Role.ADMIN)),
) -> dict:
    await svc.delete_code(db, ctx, code_id)
    await audit_service.record(
        db, action=AuditAction.DELETE, actor_user_id=ctx.user.id, workspace_id=ctx.workspace_id,
        entity_type="employee_code", entity_id=code_id, summary="Deleted employee code",
    )
    await db.commit()
    return {"ok": True}


@router.get("/label-suggestions", response_model=LabelSuggestionsOut)
async def label_suggestions(
    db: ReadSession, ctx: AuthContext = Depends(require_role(Role.MANAGER))
) -> LabelSuggestionsOut:
    """Fuzzy-grouped sheet labels that look like one person (spelling variants)."""
    return LabelSuggestionsOut(**await svc.suggest_label_groups(db, ctx))


@router.post("/merge", response_model=MergeResultOut)
async def merge_labels(
    payload: MergeLabelsIn, db: DbSession,
    ctx: AuthContext = Depends(require_role(Role.MANAGER)),
) -> MergeResultOut:
    """Fold spelling variants / alternate names of one person into one canonical label."""
    result = await svc.merge_labels(
        db, ctx, payload.canonical_label, payload.alias_labels, user_id=payload.user_id
    )
    await audit_service.record(
        db, action=AuditAction.UPDATE, actor_user_id=ctx.user.id, workspace_id=ctx.workspace_id,
        entity_type="employee_mapping", entity_id=ctx.workspace_id,
        summary=(
            f"Merged {len(result['alias_labels'])} name(s) into "
            f"'{result['canonical_label']}' ({result['rows_relabeled']} links relabeled)"
        ),
        before={"aliases": result["alias_labels"]},
        after={"canonical": result["canonical_label"],
               "user_id": str(payload.user_id) if payload.user_id else None},
    )
    await db.commit()
    return MergeResultOut(**result)


@router.patch("/mappings/{mapping_id}", response_model=EmployeeMappingOut)
async def update_mapping(
    mapping_id: uuid.UUID, payload: EmployeeMappingUpdate, db: DbSession,
    ctx: AuthContext = Depends(require_role(Role.MANAGER)),
) -> EmployeeMappingOut:
    m = await svc.update_mapping(db, ctx, mapping_id, payload)
    await audit_service.record(
        db, action=AuditAction.UPDATE, actor_user_id=ctx.user.id, workspace_id=ctx.workspace_id,
        entity_type="employee_mapping", entity_id=m.id,
        summary=f"Mapped sheet user '{m.sheet_user_label}'",
    )
    await db.commit()
    return EmployeeMappingOut(
        id=m.id, sheet_user_label=m.sheet_user_label, user_id=m.user_id,
        employee_code_id=m.employee_code_id,
    )
