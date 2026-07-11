"""Admin→user email (Phase 10 P8).

Recipient resolution is always workspace-scoped (explicit user ids, a whole
role, or a project's members), each send is one Notification row
(channel=EMAIL) so delivery status/errors live in the same log the alert
pipeline already uses, and the actual SMTP call happens on the ``alerts``
Celery queue — the API never blocks on a mail server.

Templates are a Setting KV (key="email_templates", value=[{name,subject,body}])
— the same zero-migration pattern branding/qa-settings use. ``{{full_name}}``,
``{{email}}`` and ``{{company}}`` substitute per recipient before queueing.
"""

from __future__ import annotations

import uuid

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.deps import AuthContext
from app.core.errors import ValidationAppError
from app.models.alerts import Notification
from app.models.enums import NotificationChannel, NotificationStatus
from app.models.project import ProjectMember
from app.models.settings import Setting
from app.models.user import User, WorkspaceMember

TEMPLATES_KEY = "email_templates"


def mask_email(email: str) -> str:
    """ab***@domain — enough to recognize, not enough to harvest."""
    local, _, domain = (email or "").partition("@")
    if not domain:
        return "***"
    return f"{local[:2]}***@{domain}"


def substitute(text: str, *, full_name: str, email: str, company: str) -> str:
    return (
        (text or "")
        .replace("{{full_name}}", full_name)
        .replace("{{email}}", email)
        .replace("{{company}}", company)
    )


async def resolve_recipients(
    db: AsyncSession, ctx: AuthContext, *,
    user_ids: list[uuid.UUID] | None = None,
    role: str | None = None,
    project_id: uuid.UUID | None = None,
) -> list[tuple[uuid.UUID, str, str]]:
    """(user_id, email, full_name) — deduped, active members of THIS workspace only."""
    stmt = (
        select(User.id, User.email, User.full_name)
        .join(WorkspaceMember, WorkspaceMember.user_id == User.id)
        .where(WorkspaceMember.workspace_id == ctx.workspace_id, User.is_active.is_(True))
    )
    if user_ids:
        stmt = stmt.where(User.id.in_(user_ids))
    if role:
        stmt = stmt.where(WorkspaceMember.role == role)
    if project_id is not None:
        stmt = stmt.where(
            User.id.in_(
                select(ProjectMember.user_id).where(ProjectMember.project_id == project_id)
            )
        )
    rows = (await db.execute(stmt.distinct())).all()
    return [(r[0], r[1], r[2]) for r in rows if r[1]]


async def queue_bulk(
    db: AsyncSession, ctx: AuthContext, *,
    recipients: list[tuple[uuid.UUID, str, str]], subject: str, body: str,
    company_name: str,
) -> int:
    """One Notification per recipient (status=pending) + one Celery send each."""
    if not recipients:
        raise ValidationAppError("No recipients matched")
    ids: list[uuid.UUID] = []
    for uid, email, full_name in recipients:
        n = Notification(
            workspace_id=ctx.workspace_id,
            recipient_user_id=uid,
            channel=NotificationChannel.EMAIL,
            status=NotificationStatus.PENDING,
            title=substitute(subject, full_name=full_name, email=email, company=company_name)[:400],
            body=substitute(body, full_name=full_name, email=email, company=company_name),
            payload={"kind": "admin_email", "to": email, "sent_by": str(ctx.user.id)},
        )
        db.add(n)
        await db.flush()
        ids.append(n.id)
    from app.workers.tasks.alerts import send_admin_email

    for nid in ids:
        send_admin_email.apply_async(args=[str(nid)], queue="alerts")
    return len(ids)


async def email_log(db: AsyncSession, ctx: AuthContext, *, limit: int = 100, admin: bool) -> list[dict]:
    rows = (
        await db.execute(
            select(Notification, User.email, User.full_name)
            .join(User, User.id == Notification.recipient_user_id, isouter=True)
            .where(
                Notification.workspace_id == ctx.workspace_id,
                Notification.channel == NotificationChannel.EMAIL,
            )
            .order_by(Notification.created_at.desc())
            .limit(max(1, min(limit, 500)))
        )
    ).all()
    out = []
    for n, email, full_name in rows:
        out.append({
            "id": str(n.id),
            "recipient_user_id": str(n.recipient_user_id) if n.recipient_user_id else None,
            "recipient": full_name,
            "recipient_email": (email if admin else mask_email(email)) if email else None,
            "subject": n.title,
            "status": n.status.value if hasattr(n.status, "value") else str(n.status),
            "error": n.error,
            "created_at": n.created_at.isoformat() if n.created_at else None,
            "sent_at": n.sent_at.isoformat() if n.sent_at else None,
        })
    return out


async def get_templates(db: AsyncSession, ctx: AuthContext) -> list[dict]:
    setting = (
        await db.execute(
            select(Setting).where(
                Setting.workspace_id == ctx.workspace_id, Setting.key == TEMPLATES_KEY
            )
        )
    ).scalar_one_or_none()
    value = (setting.value if setting is not None else None) or []
    return value if isinstance(value, list) else []


async def put_templates(db: AsyncSession, ctx: AuthContext, templates: list[dict]) -> list[dict]:
    clean = []
    for t in templates[:50]:
        name = str(t.get("name") or "").strip()[:80]
        subject = str(t.get("subject") or "").strip()[:200]
        body = str(t.get("body") or "").strip()[:5000]
        if name and subject and body:
            clean.append({"name": name, "subject": subject, "body": body})
    setting = (
        await db.execute(
            select(Setting).where(
                Setting.workspace_id == ctx.workspace_id, Setting.key == TEMPLATES_KEY
            )
        )
    ).scalar_one_or_none()
    if setting is None:
        setting = Setting(workspace_id=ctx.workspace_id, key=TEMPLATES_KEY, value=clean)
        db.add(setting)
    else:
        setting.value = clean
    await db.flush()
    return clean
