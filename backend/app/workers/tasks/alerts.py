"""Notification dispatch tasks for external alert channels."""

from __future__ import annotations

import asyncio
import hashlib
import hmac
import json
import smtplib
import uuid
from datetime import datetime, timezone
from email.message import EmailMessage
from typing import Any

import httpx
from sqlalchemy.exc import OperationalError

from app.core.config import settings
from app.core.logging import get_logger
from app.core.metrics import ALERTS_DISPATCHED
from app.core.security import decrypt_secret
from app.db.session import session_scope
from app.models.alerts import AlertRule, Notification
from app.models.enums import NotificationChannel, NotificationStatus
from app.workers.celery_app import celery_app
from app.workers.runtime import run_async

log = get_logger("worker.alerts")


async def _dispatch_async(notification_id: uuid.UUID) -> dict:
    async with session_scope() as s:
        notif = await s.get(Notification, notification_id)
        if notif is None:
            return {"error": "notification not found"}
        if notif.status not in (NotificationStatus.PENDING, NotificationStatus.FAILED):
            return {"status": notif.status.value}
        rule = await s.get(AlertRule, notif.alert_rule_id) if notif.alert_rule_id else None
        payload = {
            "id": notif.id,
            "channel": notif.channel,
            "title": notif.title,
            "body": notif.body or "",
            "payload": notif.payload or {},
            "config": dict(rule.channel_config or {}) if rule else {},
        }

    try:
        await _send(payload)
    except OperationalError:
        raise
    except Exception as exc:  # noqa: BLE001
        log.warning(
            "notification_dispatch_failed",
            notification_id=str(notification_id),
            channel=payload["channel"].value,
            error=repr(exc),
        )
        await _mark(notification_id, NotificationStatus.FAILED, str(exc)[:1000])
        ALERTS_DISPATCHED.labels(channel=payload["channel"].value, outcome="failed").inc()
        return {"status": "failed", "error": str(exc)}

    await _mark(notification_id, NotificationStatus.SENT, None)
    ALERTS_DISPATCHED.labels(channel=payload["channel"].value, outcome="sent").inc()
    return {"status": "sent"}


async def _send(payload: dict[str, Any]) -> None:
    channel: NotificationChannel = payload["channel"]
    if channel == NotificationChannel.IN_APP:
        return
    if channel == NotificationChannel.EMAIL:
        await asyncio.to_thread(
            _send_email, payload["config"], payload["title"], payload["body"], payload["payload"]
        )
        return
    if channel == NotificationChannel.SLACK:
        await _post_slack(payload["config"], payload["title"], payload["body"], payload["payload"])
        return
    if channel == NotificationChannel.WEBHOOK:
        await _post_webhook(payload["config"], payload["title"], payload["body"], payload["payload"])
        return
    raise ValueError(f"Unsupported notification channel: {channel}")


def _send_email(config: dict[str, Any], title: str, body: str, payload: dict[str, Any]) -> None:
    recipients = _recipients(config, payload)
    if not recipients:
        raise ValueError("Email alert has no recipients configured")

    host = config.get("smtp_host") or settings.SMTP_HOST
    if not host:
        raise ValueError("SMTP_HOST is not configured")

    port = int(config.get("smtp_port") or settings.SMTP_PORT)
    username = config.get("smtp_user") or settings.SMTP_USER
    password = _secret(config, "smtp_password") or settings.SMTP_PASSWORD
    sender = config.get("from") or settings.SMTP_FROM
    use_tls = bool(config.get("smtp_use_tls", settings.SMTP_USE_TLS))

    msg = EmailMessage()
    msg["Subject"] = title
    msg["From"] = sender
    msg["To"] = ", ".join(recipients)
    msg.set_content(f"{body}\n\nPayload:\n{json.dumps(payload, indent=2, default=str)}")

    with smtplib.SMTP(host, port, timeout=20) as smtp:
        if use_tls:
            smtp.starttls()
        if username and password:
            smtp.login(username, password)
        smtp.send_message(msg)


async def _post_slack(
    config: dict[str, Any], title: str, body: str, payload: dict[str, Any]
) -> None:
    url = (
        config.get("slack_webhook_url")
        or config.get("webhook_url")
        or config.get("url")
    )
    if not url:
        raise ValueError("Slack webhook URL is not configured")
    data = {
        "text": f"*{title}*\n{body}",
        "metadata": {"event_type": "linksentinel_alert", "event_payload": payload},
    }
    async with httpx.AsyncClient(timeout=20) as client:
        resp = await client.post(str(url), json=data)
        resp.raise_for_status()


async def _post_webhook(
    config: dict[str, Any], title: str, body: str, payload: dict[str, Any]
) -> None:
    url = config.get("webhook_url") or config.get("url")
    if not url:
        raise ValueError("Webhook URL is not configured")

    data = {"title": title, "body": body, "payload": payload}
    raw = json.dumps(data, default=str, separators=(",", ":"), sort_keys=True).encode()
    headers = {"Content-Type": "application/json", "User-Agent": settings.CRAWL_USER_AGENT}
    secret = _secret(config, "webhook_secret")
    if secret:
        headers["X-LinkSentinel-Signature"] = hmac.new(
            secret.encode(), raw, hashlib.sha256
        ).hexdigest()

    extra_headers = config.get("headers") or {}
    if isinstance(extra_headers, dict):
        headers.update({str(k): str(v) for k, v in extra_headers.items()})

    async with httpx.AsyncClient(timeout=20) as client:
        resp = await client.post(str(url), content=raw, headers=headers)
        resp.raise_for_status()


async def _mark(notification_id: uuid.UUID, status: NotificationStatus, error: str | None) -> None:
    async with session_scope() as s:
        notif = await s.get(Notification, notification_id)
        if notif is None:
            return
        notif.status = status
        notif.error = error
        if status == NotificationStatus.SENT:
            notif.sent_at = datetime.now(timezone.utc)


def _recipients(config: dict[str, Any], payload: dict[str, Any] | None = None) -> list[str]:
    # Rule config first, then recipients carried on a built-in notification, then
    # the global default list — so zero-config broken-link emails still have a To.
    raw = (
        config.get("emails")
        or config.get("recipients")
        or config.get("to")
        or (payload or {}).get("recipients")
        or settings.ALERT_DEFAULT_EMAILS
    )
    if isinstance(raw, list):
        return [str(v).strip() for v in raw if str(v).strip()]
    if isinstance(raw, str):
        return [v.strip() for v in raw.split(",") if v.strip()]
    return []


def _secret(config: dict[str, Any], key: str) -> str | None:
    value = config.get(key)
    if not value:
        return None
    try:
        return decrypt_secret(str(value))
    except Exception:  # noqa: BLE001 - supports legacy/plain dev config
        return str(value)


@celery_app.task(
    name="tasks.alerts.dispatch_notification",
    bind=True,
    acks_late=True,
    max_retries=3,
    autoretry_for=(OperationalError,),
    retry_backoff=True,
)
def dispatch_notification(self, notification_id: str) -> dict:
    return run_async(_dispatch_async(uuid.UUID(notification_id)))


# ── Admin→user email (Phase 10 P8) ──────────────────────────────────────────────
async def _send_admin_email_async(notification_id: uuid.UUID) -> dict:
    """Send ONE queued admin email (Notification channel=EMAIL) via the workspace
    SMTP settings and stamp sent/failed — same status log the alert pipeline uses."""
    from app.integrations import mailer
    from app.services import branding_service

    async with session_scope() as s:
        n = await s.get(Notification, notification_id)
        if n is None or n.channel is not NotificationChannel.EMAIL:
            return {"skipped": True}
        to = (n.payload or {}).get("to")
        if not to:
            n.status = NotificationStatus.FAILED
            n.error = "recipient email missing"
            await s.commit()
            return {"failed": True}
        branding = await branding_service.get_branding(s, n.workspace_id)
        company = branding.get("company_name") or "LinkSentinel"
        try:
            await asyncio.to_thread(
                mailer.send_email,
                to,
                n.title,
                n.body or "",
                mailer.branded_html(company, n.body or ""),
            )
            n.status = NotificationStatus.SENT
            n.sent_at = datetime.now(timezone.utc)
            n.error = None
        except Exception as exc:  # noqa: BLE001 - status row carries the failure
            n.status = NotificationStatus.FAILED
            n.error = repr(exc)[:500]
        await s.commit()
        return {"sent": n.status is NotificationStatus.SENT}


@celery_app.task(
    name="tasks.emails.send_admin_email",
    bind=True,
    acks_late=True,
    max_retries=3,
    autoretry_for=(OperationalError,),
    retry_backoff=True,
)
def send_admin_email(self, notification_id: str) -> dict:
    return run_async(_send_admin_email_async(uuid.UUID(notification_id)))
