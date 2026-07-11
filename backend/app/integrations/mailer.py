"""Workspace SMTP mailer (Phase 10 P8).

The one place NEW email features send from (admin→user email, password reset).
The alert worker keeps its own per-rule path (rules can carry their own SMTP
credentials); this module covers the workspace-level SMTP_* settings only.
Raises when SMTP is unconfigured — callers decide how to degrade (the API layer
returns a clear "SMTP is not configured" error; UI hides the features).
"""

from __future__ import annotations

import smtplib
from email.mime.multipart import MIMEMultipart
from email.mime.text import MIMEText

from app.core.config import settings
from app.core.logging import get_logger

log = get_logger("integrations.mailer")


def smtp_configured() -> bool:
    return bool(settings.SMTP_HOST)


def branded_html(company_name: str | None, body_text: str) -> str:
    """Minimal inline-styled wrapper so mail clients render something decent."""
    name = company_name or "LinkSentinel"
    paragraphs = "".join(
        f'<p style="margin:0 0 12px">{line}</p>'
        for line in body_text.split("\n")
        if line.strip()
    )
    return (
        '<div style="font-family:Arial,Helvetica,sans-serif;max-width:560px;margin:0 auto;'
        'padding:24px;color:#1e293b">'
        f'<h2 style="margin:0 0 16px;font-size:18px">{name}</h2>'
        f"{paragraphs}"
        '<hr style="border:none;border-top:1px solid #e2e8f0;margin:20px 0 10px">'
        f'<p style="font-size:12px;color:#64748b;margin:0">Sent by {name} via LinkSentinel</p>'
        "</div>"
    )


def send_email(
    to: str, subject: str, body_text: str, body_html: str | None = None,
    *, from_addr: str | None = None,
) -> None:
    """Send one email over the workspace SMTP settings. Raises on failure."""
    if not settings.SMTP_HOST:
        raise RuntimeError("SMTP is not configured (set SMTP_HOST/SMTP_* in .env)")
    sender = from_addr or settings.SMTP_FROM or (settings.SMTP_USER or "noreply@localhost")
    msg = MIMEMultipart("alternative")
    msg["Subject"] = subject[:300]
    msg["From"] = sender
    msg["To"] = to
    msg.attach(MIMEText(body_text, "plain", "utf-8"))
    if body_html:
        msg.attach(MIMEText(body_html, "html", "utf-8"))
    with smtplib.SMTP(settings.SMTP_HOST, settings.SMTP_PORT, timeout=20) as smtp:
        if settings.SMTP_USE_TLS:
            smtp.starttls()
        if settings.SMTP_USER and settings.SMTP_PASSWORD:
            smtp.login(settings.SMTP_USER, settings.SMTP_PASSWORD)
        smtp.sendmail(sender, [to], msg.as_string())
    log.info("email_sent", to=to, subject=subject[:80])
