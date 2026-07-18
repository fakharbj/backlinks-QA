"""Alert-rule and notification endpoints."""

from __future__ import annotations

import uuid
from datetime import datetime

from fastapi import APIRouter, Depends, Query, status

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
    ctx: AuthCtx,
    db: ReadSession,
    unread_only: bool = False,
    severity: str | None = Query(None),
    status: str | None = Query(None),
    project_id: uuid.UUID | None = Query(None),
    since: datetime | None = Query(None),
    limit: int = Query(100),
    offset: int = Query(0),
    personal: bool = Query(False),
) -> list[NotificationOut]:
    items = await alert_service.list_notifications(
        db, ctx, unread_only=unread_only, severity=severity, status=status,
        project_id=project_id, since=since, limit=limit, offset=offset,
        personal_only=personal,
    )
    return [NotificationOut.model_validate(n) for n in items]


@router.get("/notifications/stats")
async def notification_stats(ctx: AuthCtx, db: ReadSession) -> dict:
    return await alert_service.notification_stats(db, ctx)


@router.get("/notifications/unread-count")
async def unread_count(ctx: AuthCtx, db: ReadSession, personal: bool = Query(False)) -> dict:
    return {"count": await alert_service.unread_count(db, ctx, personal_only=personal)}


@router.post("/notifications/read-all", response_model=Message)
async def mark_all_read(ctx: AuthCtx, db: DbSession, personal: bool = Query(False)) -> Message:
    n = await alert_service.mark_all_read(db, ctx, personal_only=personal)
    await db.commit()
    return Message(message=f"Marked {n} as read")


@router.post("/notifications/{notification_id}/read", response_model=Message)
async def mark_read(notification_id: uuid.UUID, ctx: AuthCtx, db: DbSession) -> Message:
    await alert_service.mark_read(db, ctx, notification_id)
    await db.commit()
    return Message(message="Marked as read")


# ── Per-user notification preferences (0052) ──────────────────────────────────
# Personal, category-level controls on top of the notifications feed. Security
# is mandatory (server-enforced); SEO alerts are managed by the workspace's
# alert rules — the response says who manages what and why, so the UI never
# shows a dead toggle without an explanation.
@router.get("/notifications/prefs")
async def get_notification_prefs(ctx: AuthCtx, db: ReadSession) -> dict:
    from app.core.config import settings
    from app.models.user import User
    from app.services import notification_service as ns

    user = await db.get(User, ctx.user.id)
    prefs = ns.effective_prefs(user.notification_prefs if user else {})
    return {
        "prefs": prefs,
        "categories": [
            {
                "key": key,
                "label": meta["label"],
                "description": meta["description"],
                "mandatory": bool(meta.get("mandatory")),
                "mandatory_why": meta.get("mandatory_why"),
                "managed_by": meta.get("managed_by"),
                "managed_why": meta.get("managed_why"),
            }
            for key, meta in ns.CATEGORIES.items()
        ],
        # Email + digest delivery need workspace SMTP — managed by the owner.
        "email_available": bool(settings.SMTP_HOST),
        "email_managed_why": (
            None if settings.SMTP_HOST else
            "Email delivery needs the workspace SMTP settings (SMTP_HOST/USER/"
            "PASSWORD in the server configuration) — ask the workspace owner."
        ),
    }


@router.put("/notifications/prefs", response_model=Message)
async def put_notification_prefs(payload: dict, ctx: AuthCtx, db: DbSession) -> Message:
    """Partial update: {category: {enabled?, channel?, cadence?}}. Unknown
    categories are rejected; mandatory categories can never be disabled."""
    from app.core.errors import ValidationAppError
    from app.models.user import User
    from app.services import notification_service as ns

    if not isinstance(payload, dict):
        raise ValidationAppError("Send {category: {enabled, channel, cadence}}.")
    unknown = [k for k in payload if k not in ns.CATEGORIES]
    if unknown:
        raise ValidationAppError(f"Unknown notification categories: {', '.join(unknown)}")
    user = await db.get(User, ctx.user.id)
    if user is None:
        raise ValidationAppError("Account not found.")
    current = dict(user.notification_prefs or {})
    for key, patch in payload.items():
        if not isinstance(patch, dict):
            raise ValidationAppError(f"'{key}' must be an object.")
        meta = ns.CATEGORIES[key]
        cur = {**(current.get(key) if isinstance(current.get(key), dict) else {})}
        if "enabled" in patch:
            if meta.get("mandatory") and not patch["enabled"]:
                raise ValidationAppError(
                    f"'{meta['label']}' is mandatory and cannot be turned off."
                )
            cur["enabled"] = bool(patch["enabled"])
        if "channel" in patch:
            if patch["channel"] not in ("in_app", "in_app_email"):
                raise ValidationAppError("channel must be 'in_app' or 'in_app_email'.")
            cur["channel"] = patch["channel"]
        if "cadence" in patch:
            if patch["cadence"] not in ("immediate", "daily", "weekly"):
                raise ValidationAppError("cadence must be immediate, daily or weekly.")
            cur["cadence"] = patch["cadence"]
        current[key] = cur
    user.notification_prefs = current
    await db.commit()
    return Message(message="Notification preferences saved.")
