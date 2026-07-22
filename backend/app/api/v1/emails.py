"""Admin→user email endpoints (Phase 10 P8). SEND_EMAILS-gated (Admin only)."""

from __future__ import annotations

import uuid

from fastapi import APIRouter, Depends
from pydantic import BaseModel, Field

from app.core.deps import AuthContext, DbSession, ReadSession, require
from app.core.errors import ValidationAppError
from app.core.rbac import Permission
from app.integrations import mailer
from app.models.enums import AuditAction
from app.services import audit_service, branding_service, email_service

router = APIRouter(prefix="/emails", tags=["emails"])


class EmailSendIn(BaseModel):
    user_ids: list[uuid.UUID] | None = None
    role: str | None = Field(default=None, pattern="^(admin|manager|qa|viewer|intern)$")
    project_id: uuid.UUID | None = None
    subject: str = Field(min_length=1, max_length=200)
    body: str = Field(min_length=1, max_length=5000)


class EmailTemplateIn(BaseModel):
    name: str = Field(min_length=1, max_length=80)
    subject: str = Field(min_length=1, max_length=200)
    body: str = Field(min_length=1, max_length=5000)


@router.get("/status")
async def email_status(
    ctx: AuthContext = Depends(require(Permission.SEND_EMAILS)),
) -> dict:
    """Whether the mailer can actually send (SMTP_* configured on the server)."""
    return {"smtp_configured": mailer.smtp_configured()}


@router.post("/send")
async def send_emails(
    payload: EmailSendIn, db: DbSession,
    ctx: AuthContext = Depends(require(Permission.SEND_EMAILS)),
) -> dict:
    """Queue an email to explicit users, a whole role, or a project's members.
    {{full_name}} / {{email}} / {{company}} substitute per recipient."""
    if not mailer.smtp_configured():
        raise ValidationAppError(
            "SMTP is not configured — add SMTP_HOST/SMTP_* to the server .env first."
        )
    if not (payload.user_ids or payload.role or payload.project_id):
        raise ValidationAppError("Pick recipients: user_ids, a role, or a project_id.")
    recipients = await email_service.resolve_recipients(
        db, ctx, user_ids=payload.user_ids, role=payload.role, project_id=payload.project_id
    )
    branding = await branding_service.get_branding(db, ctx.workspace_id)
    queued = await email_service.queue_bulk(
        db, ctx, recipients=recipients, subject=payload.subject, body=payload.body,
        company_name=branding.get("company_name") or "LinkSentinel",
    )
    await audit_service.record(
        db, action=AuditAction.CREATE, actor_user_id=ctx.user.id, workspace_id=ctx.workspace_id,
        entity_type="email", entity_id=ctx.workspace_id,
        summary=f"Emailed {queued} user(s): {payload.subject[:60]}",
    )
    await db.commit()
    return {"queued": queued}


@router.get("/log")
async def email_log(
    db: ReadSession, limit: int = 100,
    ctx: AuthContext = Depends(require(Permission.SEND_EMAILS)),
) -> list[dict]:
    """Recent admin emails with delivery status. Addresses are shown unmasked to
    admins only (SEND_EMAILS is admin-only today, so always unmasked here — the
    mask helper guards any future widening)."""
    return await email_service.email_log(db, ctx, limit=limit, admin=True)


@router.get("/templates")
async def get_templates(
    db: ReadSession, ctx: AuthContext = Depends(require(Permission.SEND_EMAILS)),
) -> list[dict]:
    return await email_service.get_templates(db, ctx)


@router.put("/templates")
async def put_templates(
    payload: list[EmailTemplateIn], db: DbSession,
    ctx: AuthContext = Depends(require(Permission.SEND_EMAILS)),
) -> list[dict]:
    out = await email_service.put_templates(db, ctx, [t.model_dump() for t in payload])
    await db.commit()
    return out
