"""Alert rules, evaluation, and notification queries (PRD §8.12).

``evaluate`` is called by the QA/alerts worker after a crawl: it matches the
crawl's change-detection events against active rules (severity + event-type +
score-drop filters), applies dedup/quiet-hours, writes an in-app ``Notification``
plus one per configured external channel, and returns the external notifications
for the worker to dispatch.
"""

from __future__ import annotations

import uuid
from datetime import datetime, time, timedelta, timezone

from sqlalchemy import and_, func, or_, select, update
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.deps import AuthContext
from app.core.errors import NotFoundError
from app.models.alerts import AlertRule, Notification
from app.models.backlink import BacklinkRecord
from app.models.crawl import BacklinkHistory
from app.models.enums import (
    HistoryEventType,
    NotificationChannel,
    NotificationStatus,
    OverallStatus,
    Severity,
)
from app.schemas.alert import AlertRuleCreate, AlertRuleUpdate

# Events that never alert on their own (too noisy without an explicit rule).
_DEFAULT_EXCLUDED = {HistoryEventType.FIRST_CRAWL.value, HistoryEventType.SCORE_CHANGED.value}


# ── CRUD ─────────────────────────────────────────────────────────────────────────
async def list_rules(db: AsyncSession, ctx: AuthContext) -> list[AlertRule]:
    stmt = select(AlertRule).where(AlertRule.workspace_id == ctx.workspace_id)
    if ctx.allowed_project_ids is not None:
        stmt = stmt.where(AlertRule.project_id.in_(ctx.allowed_project_ids or {uuid.uuid4()}))
    return list((await db.execute(stmt.order_by(AlertRule.created_at.desc()))).scalars().all())


async def create_rule(db: AsyncSession, ctx: AuthContext, payload: AlertRuleCreate) -> AlertRule:
    from app.core.security import encrypt_secret

    if payload.project_id is not None:
        ctx.assert_project(payload.project_id)
    elif ctx.allowed_project_ids is not None:
        from app.core.errors import PermissionDeniedError

        raise PermissionDeniedError("Project-scoped users must select a project for alert rules")

    config = dict(payload.channel_config)
    for secret_key in ("smtp_password", "slack_token", "webhook_secret"):
        if config.get(secret_key):
            config[secret_key] = encrypt_secret(config[secret_key])

    rule = AlertRule(
        workspace_id=ctx.workspace_id,
        project_id=payload.project_id,
        name=payload.name,
        event_types=payload.event_types,
        min_severity=Severity(payload.min_severity),
        score_drop_threshold=payload.score_drop_threshold,
        channels=payload.channels,
        channel_config=config,
        dedup_window_minutes=payload.dedup_window_minutes,
        quiet_hours=payload.quiet_hours,
        digest_mode=payload.digest_mode,
        is_active=payload.is_active,
    )
    db.add(rule)
    await db.flush()
    return rule


async def update_rule(
    db: AsyncSession, ctx: AuthContext, rule_id: uuid.UUID, payload: AlertRuleUpdate
) -> AlertRule:
    rule = await _get_rule(db, ctx, rule_id)
    data = payload.model_dump(exclude_unset=True)
    if "min_severity" in data and data["min_severity"]:
        data["min_severity"] = Severity(data["min_severity"])
    for field, value in data.items():
        setattr(rule, field, value)
    await db.flush()
    return rule


async def delete_rule(db: AsyncSession, ctx: AuthContext, rule_id: uuid.UUID) -> None:
    await db.delete(await _get_rule(db, ctx, rule_id))


async def _get_rule(db: AsyncSession, ctx: AuthContext, rule_id: uuid.UUID) -> AlertRule:
    rule = await db.get(AlertRule, rule_id)
    if rule is None or rule.workspace_id != ctx.workspace_id:
        raise NotFoundError("Alert rule not found")
    if rule.project_id is None and ctx.allowed_project_ids is not None:
        raise NotFoundError("Alert rule not found")
    if rule.project_id is not None:
        ctx.assert_project(rule.project_id)
    return rule


# ── Notifications ─────────────────────────────────────────────────────────────────
def _notif_scope(ctx: AuthContext):
    """Base predicates: workspace + in-app + project access."""
    preds = [
        Notification.workspace_id == ctx.workspace_id,
        Notification.channel == NotificationChannel.IN_APP,
    ]
    if ctx.allowed_project_ids is not None:
        preds.append(Notification.project_id.in_(ctx.allowed_project_ids or {uuid.uuid4()}))
    return preds


async def list_notifications(
    db: AsyncSession,
    ctx: AuthContext,
    *,
    unread_only: bool = False,
    severity: str | None = None,
    status: str | None = None,
    project_id: uuid.UUID | None = None,
    since: datetime | None = None,
    limit: int = 100,
    offset: int = 0,
) -> list[Notification]:
    stmt = select(Notification).where(*_notif_scope(ctx))
    if unread_only:
        stmt = stmt.where(Notification.status != NotificationStatus.READ)
    if status:
        try:
            stmt = stmt.where(Notification.status == NotificationStatus(status))
        except ValueError:
            pass
    if severity:
        try:
            stmt = stmt.where(Notification.severity == Severity(severity))
        except ValueError:
            pass
    if project_id is not None:
        ctx.assert_project(project_id)
        stmt = stmt.where(Notification.project_id == project_id)
    if since is not None:
        stmt = stmt.where(Notification.created_at >= since)
    stmt = stmt.order_by(Notification.created_at.desc()).limit(max(1, min(limit, 500))).offset(max(0, offset))
    return list((await db.execute(stmt)).scalars().all())


async def unread_count(db: AsyncSession, ctx: AuthContext) -> int:
    stmt = select(func.count(Notification.id)).where(
        *_notif_scope(ctx), Notification.status != NotificationStatus.READ
    )
    return int((await db.execute(stmt)).scalar_one())


async def notification_stats(db: AsyncSession, ctx: AuthContext) -> dict:
    """Headline counts for the notification center (total, unread, by severity/status)."""
    total = int((await db.execute(select(func.count(Notification.id)).where(*_notif_scope(ctx)))).scalar_one())
    unread = await unread_count(db, ctx)
    by_severity: dict[str, int] = {}
    rows = (
        await db.execute(
            select(Notification.severity, func.count(Notification.id))
            .where(*_notif_scope(ctx))
            .group_by(Notification.severity)
        )
    ).all()
    for sev, n in rows:
        by_severity[sev.value if sev is not None else "INFO"] = int(n)
    return {"total": total, "unread": unread, "by_severity": by_severity}


async def mark_all_read(db: AsyncSession, ctx: AuthContext) -> int:
    stmt = (
        update(Notification)
        .where(*_notif_scope(ctx), Notification.status != NotificationStatus.READ)
        .values(status=NotificationStatus.READ, read_at=datetime.now(timezone.utc))
    )
    result = await db.execute(stmt)
    await db.flush()
    return int(result.rowcount or 0)


async def mark_read(db: AsyncSession, ctx: AuthContext, notification_id: uuid.UUID) -> None:
    notif = await db.get(Notification, notification_id)
    if notif is None or notif.workspace_id != ctx.workspace_id:
        raise NotFoundError("Notification not found")
    if notif.project_id is not None:
        ctx.assert_project(notif.project_id)
    elif ctx.allowed_project_ids is not None:
        raise NotFoundError("Notification not found")
    notif.status = NotificationStatus.READ
    notif.read_at = datetime.now(timezone.utc)
    await db.flush()


# ── Evaluation (worker side) ──────────────────────────────────────────────────────
async def evaluate(
    db: AsyncSession, backlink: BacklinkRecord, events: list[BacklinkHistory]
) -> list[Notification]:
    """Match events against rules; return external-channel notifications to dispatch."""
    if not events:
        return []

    rules = (
        await db.execute(
            select(AlertRule).where(
                AlertRule.workspace_id == backlink.workspace_id,
                AlertRule.is_active.is_(True),
                or_(
                    AlertRule.project_id.is_(None),
                    AlertRule.project_id == backlink.project_id,
                ),
            )
        )
    ).scalars().all()
    if not rules:
        return []

    to_dispatch: list[Notification] = []
    now = datetime.now(timezone.utc)

    for rule in rules:
        if _in_quiet_hours(rule, now):
            continue
        matched = [ev for ev in events if _event_matches(rule, ev)]
        if not matched:
            continue
        top = max(matched, key=lambda e: (e.severity.rank if e.severity else 0))
        dedup_key = f"{rule.id}:{backlink.id}:{top.event_type.value}"
        if await _is_duplicate(db, dedup_key, rule.dedup_window_minutes, now):
            continue

        title, body = _render(backlink, top, matched)
        # In-app notification always created.
        db.add(_make_notification(rule, backlink, top, NotificationChannel.IN_APP, title, body,
                                  dedup_key, status=NotificationStatus.SENT, sent_at=now))
        # External channels created pending; returned for the worker to dispatch.
        for channel in rule.channels:
            if channel == NotificationChannel.IN_APP.value:
                continue
            notif = _make_notification(
                rule, backlink, top, NotificationChannel(channel), title, body, dedup_key,
                status=NotificationStatus.PENDING,
            )
            db.add(notif)
            to_dispatch.append(notif)

    await db.flush()
    return to_dispatch


# ── Built-in zero-config alerting (PRD §8.12, broken-link lifecycle) ───────────────
# HTTP statuses we treat as "the page is genuinely broken" (worth an email). 403/401
# are deliberately excluded — they are bot/auth blocks routed to manual review, not
# proof the link is gone, so they raise an in-app flag but do not email the team.
_BROKEN_HTTP = {404, 410, 500, 502, 503, 504, 520, 521, 522, 523, 524, 525, 526, 530}


async def evaluate_builtin(
    db: AsyncSession, backlink: BacklinkRecord
) -> list[Notification]:
    """Zero-config alerting that runs on *every* crawl (no rule needed).

    • Broken / removed / server-error  → in-app alert + email (if SMTP set).
    • Still broken on a later scan      → re-alert, at most once per
      ``ALERT_RENOTIFY_HOURS`` so the team is reminded without being spammed.
    • Recovered after being broken      → a single "back up" note.

    Returns the external (email) notifications for the worker to dispatch.
    """
    from app.core.config import settings

    if not settings.ALERT_DEFAULT_ENABLED:
        return []

    broken = (
        backlink.link_found is False
        or backlink.status == OverallStatus.FAIL
        or (backlink.http_status is not None and backlink.http_status in _BROKEN_HTTP)
    )
    now = datetime.now(timezone.utc)
    window = timedelta(hours=max(1, settings.ALERT_RENOTIFY_HOURS))
    to_dispatch: list[Notification] = []

    if broken:
        dedup_key = f"builtin:{backlink.id}:broken"
        last = await _last_builtin(db, dedup_key)
        if last is not None and (now - last) < window:
            return []  # already alerted recently — wait out the re-notify window
        reason = _broken_reason(backlink)
        title = f"[Backlink broken] {backlink.source_page_url}"
        body = (
            f"{reason}\n\n"
            f"Source page: {backlink.source_page_url}\n"
            f"Target link: {backlink.target_url}\n"
            f"Status: {backlink.status.value}  •  HTTP: {backlink.http_status}  "
            f"•  Consecutive failures: {backlink.consecutive_failures}\n\n"
            "We will keep checking it on every scan and email again if it stays broken."
        )
        to_dispatch += await _emit_builtin(
            db, backlink, dedup_key, title, body, Severity.CRITICAL, now
        )
    else:
        # Recovery: only if it was broken more recently than our last "recovered".
        broke_at = await _last_builtin(db, f"builtin:{backlink.id}:broken")
        if broke_at is not None:
            healed_at = await _last_builtin(db, f"builtin:{backlink.id}:recovered")
            if healed_at is None or broke_at > healed_at:
                dedup_key = f"builtin:{backlink.id}:recovered"
                title = f"[Backlink recovered] {backlink.source_page_url}"
                body = (
                    "Good news — this backlink is healthy again.\n\n"
                    f"Source page: {backlink.source_page_url}\n"
                    f"Target link: {backlink.target_url}\n"
                    f"Status: {backlink.status.value}  •  HTTP: {backlink.http_status}"
                )
                to_dispatch += await _emit_builtin(
                    db, backlink, dedup_key, title, body, Severity.INFO, now
                )

    return to_dispatch


def _broken_reason(backlink: BacklinkRecord) -> str:
    if backlink.link_found is False:
        return "The backlink to your site was not found on the source page (removed)."
    if backlink.http_status is not None and backlink.http_status in _BROKEN_HTTP:
        return f"The source page is not loading (HTTP {backlink.http_status})."
    return "The backlink failed our quality checks and needs attention."


async def _emit_builtin(
    db: AsyncSession,
    backlink: BacklinkRecord,
    dedup_key: str,
    title: str,
    body: str,
    severity: Severity,
    now: datetime,
) -> list[Notification]:
    from app.core.config import settings

    payload = {
        "builtin": True,
        "source_page_url": backlink.source_page_url,
        "target_url": backlink.target_url,
        "http_status": backlink.http_status,
        "status": backlink.status.value,
    }
    # In-app alert — always, so the Alerts tab works with no setup.
    db.add(
        Notification(
            workspace_id=backlink.workspace_id, project_id=backlink.project_id,
            backlink_id=backlink.id, alert_rule_id=None,
            channel=NotificationChannel.IN_APP, status=NotificationStatus.SENT,
            severity=severity, title=title[:400], body=body, dedup_key=dedup_key,
            sent_at=now, payload=payload,
        )
    )

    dispatch: list[Notification] = []
    recipients = await _default_recipients(db, backlink.workspace_id)
    if settings.SMTP_HOST and recipients:
        email_notif = Notification(
            workspace_id=backlink.workspace_id, project_id=backlink.project_id,
            backlink_id=backlink.id, alert_rule_id=None,
            channel=NotificationChannel.EMAIL, status=NotificationStatus.PENDING,
            severity=severity, title=title[:400], body=body, dedup_key=dedup_key,
            payload={**payload, "recipients": recipients},
        )
        db.add(email_notif)
        dispatch.append(email_notif)

    await db.flush()
    return dispatch


async def _last_builtin(db: AsyncSession, dedup_key: str) -> datetime | None:
    """Most recent created_at for a built-in notification with this dedup key."""
    return (
        await db.execute(
            select(Notification.created_at)
            .where(Notification.dedup_key == dedup_key)
            .order_by(Notification.created_at.desc())
            .limit(1)
        )
    ).scalar_one_or_none()


async def _default_recipients(db: AsyncSession, workspace_id: uuid.UUID) -> list[str]:
    """Built-in email recipients: the configured list, else every active member."""
    from app.core.config import settings
    from app.models.user import User, WorkspaceMember

    if settings.ALERT_DEFAULT_EMAILS:
        return list(settings.ALERT_DEFAULT_EMAILS)
    rows = (
        await db.execute(
            select(User.email)
            .join(WorkspaceMember, WorkspaceMember.user_id == User.id)
            .where(WorkspaceMember.workspace_id == workspace_id, User.is_active.is_(True))
        )
    ).scalars().all()
    return [e for e in rows if e]


def _event_matches(rule: AlertRule, ev: BacklinkHistory) -> bool:
    etype = ev.event_type.value
    if rule.event_types:
        if etype not in rule.event_types:
            return False
    elif etype in _DEFAULT_EXCLUDED:
        return False

    if etype == HistoryEventType.SCORE_CHANGED.value and rule.score_drop_threshold:
        return ev.score_delta is not None and ev.score_delta <= -abs(rule.score_drop_threshold)

    if ev.severity is None:
        return False
    return ev.severity.rank >= rule.min_severity.rank


async def _is_duplicate(
    db: AsyncSession, dedup_key: str, window_minutes: int, now: datetime
) -> bool:
    since = now - timedelta(minutes=window_minutes)
    existing = (
        await db.execute(
            select(Notification.id).where(
                and_(Notification.dedup_key == dedup_key, Notification.created_at >= since)
            ).limit(1)
        )
    ).scalar_one_or_none()
    return existing is not None


def _in_quiet_hours(rule: AlertRule, now: datetime) -> bool:
    qh = rule.quiet_hours or {}
    start, end = qh.get("start"), qh.get("end")
    if start is None or end is None:
        return False
    try:
        s = time.fromisoformat(str(start))
        e = time.fromisoformat(str(end))
    except ValueError:
        return False
    cur = now.timetz().replace(tzinfo=None)
    return (s <= cur < e) if s <= e else (cur >= s or cur < e)


def _make_notification(
    rule: AlertRule, backlink: BacklinkRecord, ev: BacklinkHistory,
    channel: NotificationChannel, title: str, body: str, dedup_key: str,
    *, status: NotificationStatus, sent_at: datetime | None = None,
) -> Notification:
    return Notification(
        workspace_id=backlink.workspace_id,
        project_id=backlink.project_id,
        backlink_id=backlink.id,
        alert_rule_id=rule.id,
        channel=channel,
        status=status,
        severity=ev.severity,
        title=title,
        body=body,
        dedup_key=dedup_key,
        sent_at=sent_at,
        payload={
            "event_type": ev.event_type.value,
            "old": ev.old_value,
            "new": ev.new_value,
            "source_page_url": backlink.source_page_url,
            "target_url": backlink.target_url,
        },
    )


def _render(
    backlink: BacklinkRecord, top: BacklinkHistory, matched: list[BacklinkHistory]
) -> tuple[str, str]:
    title = f"[{top.event_type.value.replace('_', ' ').title()}] {backlink.source_page_url}"
    lines = [f"Backlink: {backlink.source_page_url} → {backlink.target_url}"]
    for ev in matched:
        change = f"{ev.field}: {ev.old_value} → {ev.new_value}" if ev.field else ev.event_type.value
        lines.append(f"• {ev.event_type.value}: {change}")
    return title[:400], "\n".join(lines)
