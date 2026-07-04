"""Employee code catalog + sheet-user reconciliation (Phase 8, feature 3).

``sync_from_data`` backfills the catalog + mappings from whatever is already on the
backlinks (the sheet "User" label + "Employee Code"), auto-linking a label to an
app user when import previously resolved it (``assigned_user_id``). The rest is
tenant-scoped CRUD with code-uniqueness validation.
"""

from __future__ import annotations

import uuid

from sqlalchemy import String, cast, func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.deps import AuthContext
from app.core.errors import ConflictError, NotFoundError
from app.models.backlink import BacklinkRecord
from app.models.employee import EmployeeCode, UserEmployeeMapping
from app.models.user import User, WorkspaceMember
from app.schemas.employee import EmployeeCodeCreate, EmployeeCodeUpdate, EmployeeMappingUpdate


async def _app_users(db: AsyncSession, workspace_id: uuid.UUID) -> list[dict]:
    rows = (
        await db.execute(
            select(User.id, User.full_name, User.email)
            .join(WorkspaceMember, WorkspaceMember.user_id == User.id)
            .where(WorkspaceMember.workspace_id == workspace_id)
            .order_by(User.full_name.asc())
        )
    ).all()
    return [{"id": uid, "name": name, "email": email} for uid, name, email in rows]


async def overview(db: AsyncSession, ctx: AuthContext) -> dict:
    users = await _app_users(db, ctx.workspace_id)
    name_by_id = {u["id"]: (u["name"] or u["email"]) for u in users}

    codes = list(
        (
            await db.execute(
                select(EmployeeCode)
                .where(
                    EmployeeCode.workspace_id == ctx.workspace_id,
                    EmployeeCode.deleted_at.is_(None),
                )
                .order_by(EmployeeCode.code.asc())
            )
        ).scalars().all()
    )

    mappings = list(
        (
            await db.execute(
                select(UserEmployeeMapping)
                .where(UserEmployeeMapping.workspace_id == ctx.workspace_id)
                .order_by(UserEmployeeMapping.sheet_user_label.asc())
            )
        ).scalars().all()
    )

    # Backlink counts per sheet label (one grouped query, not per-row).
    counts = dict(
        (
            await db.execute(
                select(BacklinkRecord.assigned_user_label, func.count())
                .where(
                    BacklinkRecord.workspace_id == ctx.workspace_id,
                    BacklinkRecord.assigned_user_label.is_not(None),
                )
                .group_by(BacklinkRecord.assigned_user_label)
            )
        ).all()
    )

    return {
        "codes": [
            {
                "id": c.id, "code": c.code, "display_name": c.display_name,
                "user_id": c.user_id, "user_name": name_by_id.get(c.user_id),
                "is_active": c.is_active,
            }
            for c in codes
        ],
        "mappings": [
            {
                "id": m.id, "sheet_user_label": m.sheet_user_label, "user_id": m.user_id,
                "user_name": name_by_id.get(m.user_id),
                "employee_code_id": m.employee_code_id,
                "is_active": m.is_active,
                "backlink_count": int(counts.get(m.sheet_user_label, 0)),
            }
            for m in mappings
        ],
        "app_users": users,
    }


async def sync_from_data(db: AsyncSession, ctx: AuthContext) -> dict:
    """Backfill codes + label mappings from current backlink data (idempotent)."""
    existing_codes = set(
        (
            await db.execute(
                select(EmployeeCode.code).where(EmployeeCode.workspace_id == ctx.workspace_id)
            )
        ).scalars().all()
    )
    code_rows = (
        await db.execute(
            select(func.distinct(BacklinkRecord.employee_code)).where(
                BacklinkRecord.workspace_id == ctx.workspace_id,
                BacklinkRecord.employee_code.is_not(None),
                BacklinkRecord.employee_code != "",
            )
        )
    ).scalars().all()
    new_codes = 0
    for raw in code_rows:
        code = (raw or "").strip()
        if code and code not in existing_codes:
            db.add(EmployeeCode(workspace_id=ctx.workspace_id, code=code))
            existing_codes.add(code)
            new_codes += 1

    existing_labels = set(
        (
            await db.execute(
                select(UserEmployeeMapping.sheet_user_label).where(
                    UserEmployeeMapping.workspace_id == ctx.workspace_id
                )
            )
        ).scalars().all()
    )
    label_rows = (
        await db.execute(
            select(
                BacklinkRecord.assigned_user_label,
                func.min(cast(BacklinkRecord.assigned_user_id, String)),
            )
            .where(
                BacklinkRecord.workspace_id == ctx.workspace_id,
                BacklinkRecord.assigned_user_label.is_not(None),
                BacklinkRecord.assigned_user_label != "",
            )
            .group_by(BacklinkRecord.assigned_user_label)
        )
    ).all()
    new_maps = 0
    for label, any_user in label_rows:
        lbl = (label or "").strip()
        if lbl and lbl not in existing_labels:
            uid = uuid.UUID(any_user) if any_user else None
            db.add(
                UserEmployeeMapping(
                    workspace_id=ctx.workspace_id, sheet_user_label=lbl, user_id=uid
                )
            )
            existing_labels.add(lbl)
            new_maps += 1

    await db.flush()
    return {"new_codes": new_codes, "new_mappings": new_maps}


async def create_code(db: AsyncSession, ctx: AuthContext, payload: EmployeeCodeCreate) -> EmployeeCode:
    code = payload.code.strip()
    exists = (
        await db.execute(
            select(EmployeeCode).where(
                EmployeeCode.workspace_id == ctx.workspace_id,
                EmployeeCode.code == code,
                EmployeeCode.deleted_at.is_(None),
            )
        )
    ).scalar_one_or_none()
    if exists is not None:
        raise ConflictError("That employee code already exists")
    ec = EmployeeCode(
        workspace_id=ctx.workspace_id, code=code,
        display_name=payload.display_name, user_id=payload.user_id,
    )
    db.add(ec)
    await db.flush()
    return ec


async def _get_code(db: AsyncSession, ctx: AuthContext, code_id: uuid.UUID) -> EmployeeCode:
    ec = await db.get(EmployeeCode, code_id)
    if ec is None or ec.workspace_id != ctx.workspace_id or ec.deleted_at is not None:
        raise NotFoundError("Employee code not found")
    return ec


async def update_code(
    db: AsyncSession, ctx: AuthContext, code_id: uuid.UUID, payload: EmployeeCodeUpdate
) -> EmployeeCode:
    ec = await _get_code(db, ctx, code_id)
    for field, value in payload.model_dump(exclude_unset=True).items():
        setattr(ec, field, value)
    await db.flush()
    return ec


async def delete_code(db: AsyncSession, ctx: AuthContext, code_id: uuid.UUID) -> None:
    from datetime import datetime, timezone

    ec = await _get_code(db, ctx, code_id)
    ec.deleted_at = datetime.now(timezone.utc)
    ec.deleted_by = ctx.user.id
    ec.is_active = False
    await db.flush()


async def update_mapping(
    db: AsyncSession, ctx: AuthContext, mapping_id: uuid.UUID, payload: EmployeeMappingUpdate
) -> UserEmployeeMapping:
    m = await db.get(UserEmployeeMapping, mapping_id)
    if m is None or m.workspace_id != ctx.workspace_id:
        raise NotFoundError("Mapping not found")
    for field, value in payload.model_dump(exclude_unset=True).items():
        setattr(m, field, value)
    await db.flush()
    return m
