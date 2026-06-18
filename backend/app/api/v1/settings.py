"""Workspace settings + audit-log access (Admin)."""

from __future__ import annotations

from fastapi import APIRouter, Depends, Query
from pydantic import BaseModel
from sqlalchemy import select

from app.core.deps import AuthContext, AuthCtx, DbSession, ReadSession, require_role
from app.core.rbac import Role
from app.core.security import encrypt_secret
from app.models.audit import AuditLog
from app.models.settings import Setting
from app.schemas.common import Message

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
