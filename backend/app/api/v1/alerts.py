"""Alert-rule and notification endpoints."""

from __future__ import annotations

import uuid

from fastapi import APIRouter, Depends, status

from app.core.deps import AuthContext, AuthCtx, DbSession, ReadSession, require
from app.core.rbac import Permission
from app.schemas.alert import (
    AlertRuleCreate,
    AlertRuleOut,
    AlertRuleUpdate,
    NotificationOut,
)
from app.schemas.common import Message
from app.services import alert_service

router = APIRouter(tags=["alerts"])


@router.get("/alert-rules", response_model=list[AlertRuleOut])
async def list_rules(ctx: AuthCtx, db: ReadSession) -> list[AlertRuleOut]:
    return [AlertRuleOut.model_validate(r) for r in await alert_service.list_rules(db, ctx)]


@router.post("/alert-rules", response_model=AlertRuleOut, status_code=status.HTTP_201_CREATED)
async def create_rule(
    payload: AlertRuleCreate, db: DbSession,
    ctx: AuthContext = Depends(require(Permission.CONFIGURE_ALERTS)),
) -> AlertRuleOut:
    rule = await alert_service.create_rule(db, ctx, payload)
    await db.commit()
    return AlertRuleOut.model_validate(rule)


@router.patch("/alert-rules/{rule_id}", response_model=AlertRuleOut)
async def update_rule(
    rule_id: uuid.UUID, payload: AlertRuleUpdate, db: DbSession,
    ctx: AuthContext = Depends(require(Permission.CONFIGURE_ALERTS)),
) -> AlertRuleOut:
    rule = await alert_service.update_rule(db, ctx, rule_id, payload)
    await db.commit()
    return AlertRuleOut.model_validate(rule)


@router.delete("/alert-rules/{rule_id}", response_model=Message)
async def delete_rule(
    rule_id: uuid.UUID, db: DbSession,
    ctx: AuthContext = Depends(require(Permission.CONFIGURE_ALERTS)),
) -> Message:
    await alert_service.delete_rule(db, ctx, rule_id)
    await db.commit()
    return Message(message="Alert rule deleted")


@router.get("/notifications", response_model=list[NotificationOut])
async def list_notifications(
    ctx: AuthCtx, db: ReadSession, unread_only: bool = False
) -> list[NotificationOut]:
    items = await alert_service.list_notifications(db, ctx, unread_only=unread_only)
    return [NotificationOut.model_validate(n) for n in items]


@router.get("/notifications/unread-count")
async def unread_count(ctx: AuthCtx, db: ReadSession) -> dict:
    return {"count": await alert_service.unread_count(db, ctx)}


@router.post("/notifications/{notification_id}/read", response_model=Message)
async def mark_read(notification_id: uuid.UUID, ctx: AuthCtx, db: DbSession) -> Message:
    await alert_service.mark_read(db, ctx, notification_id)
    await db.commit()
    return Message(message="Marked as read")
