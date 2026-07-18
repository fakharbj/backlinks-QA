"""User-facing notifications on top of the existing ``notifications`` table.

The alert engine already writes SEO-regression notifications (broadcast,
``recipient_user_id`` NULL). This module adds PERSONAL, category-tagged
notifications for the platform's own events — task assigned, leave
request/decision, QA check finished, sync failure, report ready, security —
respecting each recipient's per-user preferences (``users.notification_prefs``).

Like ``batch_service``, every write here is FAIL-OPEN: a notification problem
must never break the action that triggered it. Helpers open their own short
sessions so they can be called from workers and request handlers alike.
"""

from __future__ import annotations

import uuid
from datetime import datetime, timezone

from sqlalchemy import select

from app.core.logging import get_logger
from app.db.session import session_scope
from app.models.alerts import Notification
from app.models.enums import NotificationChannel, NotificationStatus

log = get_logger("services.notification")

# The categories this platform ACTUALLY emits. mandatory=True → the API refuses
# to disable it (security events must always reach the account owner).
# managed_by → delivery is governed elsewhere; the prefs UI explains WHO and WHY
# instead of showing a dead toggle.
CATEGORIES: dict[str, dict] = {
    "task_assigned": {
        "label": "Task assigned to you",
        "description": "A manager planned work for you (new day/project assignment).",
        "mandatory": False,
    },
    "task_changed": {
        "label": "Your task changed",
        "description": "An existing assignment of yours was edited (hours, types, target).",
        "mandatory": False,
    },
    "leave_request": {
        "label": "Leave request (approvals)",
        "description": "Someone on the team asked for days off — you can approve or reject it.",
        "mandatory": False,
        "audience": "managers",
    },
    "leave_decision": {
        "label": "Leave approved / rejected",
        "description": "The decision on YOUR leave request.",
        "mandatory": False,
    },
    "qa_check_done": {
        "label": "QA / index check finished",
        "description": "A crawl, QA check or index check you started has finished.",
        "mandatory": False,
    },
    "sync_failed": {
        "label": "Sheet sync problem",
        "description": "A sheet sync (single or bulk) finished with failures.",
        "mandatory": False,
    },
    "report_ready": {
        "label": "Report ready",
        "description": "A report you generated is ready to download.",
        "mandatory": False,
    },
    "seo_alert": {
        "label": "Critical SEO alert",
        "description": "Link lost, status regression or other rule-based alerts.",
        "mandatory": False,
        # These rows are produced by the Alert-rules engine — per-rule channels,
        # dedup windows and quiet hours live there, not in personal prefs.
        "managed_by": "Workspace alert rules (Alerts desk)",
        "managed_why": "Delivery, dedup and quiet hours are configured per alert rule "
                       "so the whole team sees the same signal.",
    },
    "security": {
        "label": "Security alerts",
        "description": "Password resets, login-email changes and lockouts on YOUR account.",
        "mandatory": True,
        "mandatory_why": "Account-security events can't be muted — if someone changes "
                         "your login you must know.",
    },
}

_DEFAULT_PREF = {"enabled": True, "channel": "in_app", "cadence": "immediate"}


def effective_prefs(raw: dict | None) -> dict[str, dict]:
    """The user's stored prefs merged over the defaults — one entry per known
    category, mandatory ones forced on."""
    out: dict[str, dict] = {}
    stored = raw if isinstance(raw, dict) else {}
    for key, meta in CATEGORIES.items():
        cur = {**_DEFAULT_PREF, **(stored.get(key) if isinstance(stored.get(key), dict) else {})}
        if meta.get("mandatory"):
            cur["enabled"] = True
        out[key] = {
            "enabled": bool(cur.get("enabled", True)),
            "channel": cur.get("channel") if cur.get("channel") in ("in_app", "in_app_email") else "in_app",
            "cadence": cur.get("cadence") if cur.get("cadence") in ("immediate", "daily", "weekly") else "immediate",
        }
    return out


async def _admin_user_ids(s, workspace_id: uuid.UUID, *, include_managers: bool = False) -> list[uuid.UUID]:
    from app.models.user import User, WorkspaceMember

    roles = {"admin", "manager"} if include_managers else {"admin"}
    rows = (
        await s.execute(
            select(WorkspaceMember.user_id, WorkspaceMember.role)
            .join(User, User.id == WorkspaceMember.user_id)
            .where(WorkspaceMember.workspace_id == workspace_id, User.is_active.is_(True))
        )
    ).all()
    return [uid for uid, role in rows if str(getattr(role, "value", role)) in roles]


async def user_id_for_label(s, workspace_id: uuid.UUID, label: str) -> uuid.UUID | None:
    """The login linked to a sheet-user label (canonical catalog row only)."""
    from app.models.employee import UserEmployeeMapping

    return (
        await s.execute(
            select(UserEmployeeMapping.user_id).where(
                UserEmployeeMapping.workspace_id == workspace_id,
                UserEmployeeMapping.sheet_user_label == (label or "").strip().lower(),
                UserEmployeeMapping.canonical_label.is_(None),
                UserEmployeeMapping.user_id.isnot(None),
            )
        )
    ).scalars().first()


async def notify(
    workspace_id: uuid.UUID,
    category: str,
    title: str,
    *,
    user_ids: list[uuid.UUID] | None = None,
    to_admins: bool = False,
    include_managers: bool = False,
    exclude_user_id: uuid.UUID | None = None,
    body: str | None = None,
    project_id: uuid.UUID | None = None,
    ref: dict | None = None,
    severity=None,
) -> int:
    """Insert in-app notifications for each recipient whose prefs allow the
    category (mandatory categories always deliver). Returns rows written.
    FAIL-OPEN — never raises."""
    try:
        from app.core.config import settings
        from app.models.user import User

        meta = CATEGORIES.get(category) or {}
        async with session_scope() as s:
            recipients: list[uuid.UUID] = list(user_ids or [])
            if to_admins:
                recipients += await _admin_user_ids(
                    s, workspace_id, include_managers=include_managers
                )
            recipients = [u for u in dict.fromkeys(recipients) if u and u != exclude_user_id]
            if not recipients:
                return 0
            users = {
                u.id: u
                for u in (
                    await s.execute(select(User).where(User.id.in_(recipients)))
                ).scalars().all()
            }
            now = datetime.now(timezone.utc)
            written = 0
            for uid in recipients:
                u = users.get(uid)
                if u is None or not u.is_active:
                    continue
                pref = effective_prefs(u.notification_prefs).get(category, _DEFAULT_PREF)
                if not pref["enabled"] and not meta.get("mandatory"):
                    continue
                s.add(Notification(
                    workspace_id=workspace_id, project_id=project_id,
                    recipient_user_id=uid,
                    channel=NotificationChannel.IN_APP,
                    status=NotificationStatus.SENT, sent_at=now,
                    severity=severity, title=title[:400], body=body,
                    payload={"category": category, **({"ref": ref} if ref else {})},
                ))
                written += 1
                # Immediate e-mail mirror — only when the user opted in AND the
                # workspace has SMTP. Digest cadences are stored but need SMTP
                # + the digest job, so they stay in-app-only for now.
                if (
                    pref["channel"] == "in_app_email"
                    and pref["cadence"] == "immediate"
                    and settings.SMTP_HOST
                ):
                    try:
                        from app.integrations.mailer import send_email

                        send_email(u.email, title[:200], body or title)
                    except Exception as exc:  # noqa: BLE001 — email is best-effort
                        log.warning("notify_email_failed", user=str(uid), error=repr(exc))
            return written
    except Exception as exc:  # noqa: BLE001 — fail-open by design
        log.warning("notify_failed", category=category, error=repr(exc))
        return 0
