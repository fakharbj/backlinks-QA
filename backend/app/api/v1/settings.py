"""Workspace settings + audit-log access (Admin)."""

from __future__ import annotations

from fastapi import APIRouter, Depends, Query
from pydantic import BaseModel
from sqlalchemy import select

from app.core.deps import AuthContext, AuthCtx, DbSession, ReadSession, require_role
from app.core.rbac import Role
from app.core.security import encrypt_secret
from app.models.audit import AuditLog
from app.models.enums import AuditAction
from app.models.settings import Setting
from app.schemas.common import Message
from app.services import audit_service, qa_settings_service

router = APIRouter(tags=["settings"])


class SettingUpsert(BaseModel):
    key: str
    value: dict
    is_secret: bool = False


class SettingOut(BaseModel):
    key: str
    value: dict
    is_secret: bool


class AuditLogOut(BaseModel):
    action: str
    entity_type: str | None
    entity_id: str | None
    summary: str | None
    actor_user_id: str | None
    created_at: str


@router.get("/settings", response_model=list[SettingOut])
async def list_settings(ctx: AuthCtx, db: ReadSession) -> list[SettingOut]:
    rows = (
        await db.execute(select(Setting).where(Setting.workspace_id == ctx.workspace_id))
    ).scalars().all()
    out: list[SettingOut] = []
    for s in rows:
        value = {"_secret": True} if s.is_secret else s.value
        out.append(SettingOut(key=s.key, value=value, is_secret=s.is_secret))
    return out


@router.put("/settings", response_model=Message)
async def upsert_setting(
    payload: SettingUpsert, db: DbSession,
    ctx: AuthContext = Depends(require_role(Role.ADMIN)),
) -> Message:
    existing = (
        await db.execute(
            select(Setting).where(
                Setting.workspace_id == ctx.workspace_id, Setting.key == payload.key
            )
        )
    ).scalar_one_or_none()
    value = payload.value
    if payload.is_secret:
        value = {
            k: (encrypt_secret(v) if isinstance(v, str) else v) for k, v in payload.value.items()
        }
    if existing is None:
        db.add(
            Setting(
                workspace_id=ctx.workspace_id, key=payload.key, value=value,
                is_secret=payload.is_secret,
            )
        )
    else:
        existing.value = value
        existing.is_secret = payload.is_secret
    await db.commit()
    return Message(message="Setting saved")


class QaSettingsIn(BaseModel):
    overrides: dict


@router.get("/qa-settings")
async def get_qa_settings(ctx: AuthCtx, db: ReadSession) -> dict:
    """Effective QA execution knobs (config defaults + this workspace's overrides)
    with per-knob default/min/max metadata for the admin editor."""
    return await qa_settings_service.describe(db, ctx.workspace_id)


@router.put("/qa-settings")
async def put_qa_settings(
    payload: QaSettingsIn, db: DbSession,
    ctx: AuthContext = Depends(require_role(Role.ADMIN)),
) -> dict:
    """Save QA execution overrides (admin). Unknown keys ignored; each value is
    coerced + clamped to its safe range; a null value clears that override."""
    result = await qa_settings_service.save(db, ctx.workspace_id, payload.overrides or {})
    await audit_service.record(
        db, action=AuditAction.UPDATE, actor_user_id=ctx.user.id,
        workspace_id=ctx.workspace_id, entity_type="qa_settings", entity_id=ctx.workspace_id,
        summary="Updated QA execution settings",
    )
    await db.commit()
    return result


@router.get("/audit-logs", response_model=list[AuditLogOut])
async def list_audit_logs(
    db: ReadSession,
    ctx: AuthContext = Depends(require_role(Role.MANAGER)),
    limit: int = Query(default=100, ge=1, le=500),
) -> list[AuditLogOut]:
    rows = (
        await db.execute(
            select(AuditLog)
            .where(AuditLog.workspace_id == ctx.workspace_id)
            .order_by(AuditLog.created_at.desc())
            .limit(limit)
        )
    ).scalars().all()
    return [
        AuditLogOut(
            action=r.action.value, entity_type=r.entity_type, entity_id=r.entity_id,
            summary=r.summary, actor_user_id=str(r.actor_user_id) if r.actor_user_id else None,
            created_at=r.created_at.isoformat(),
        )
        for r in rows
    ]
