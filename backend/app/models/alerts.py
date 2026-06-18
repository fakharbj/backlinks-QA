"""Alert rules + notifications (PRD §8.12)."""

from __future__ import annotations

import uuid
from datetime import datetime

from sqlalchemy import Boolean, DateTime, ForeignKey, Index, Integer, String, Text, func
from sqlalchemy.dialects.postgresql import ARRAY, JSONB
from sqlalchemy.dialects.postgresql import UUID as PGUUID
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base, TimestampMixin, UUIDPrimaryKeyMixin
from app.db.types import pg_enum
from app.models.enums import NotificationChannel, NotificationStatus, Severity


class AlertRule(UUIDPrimaryKeyMixin, TimestampMixin, Base):
    __tablename__ = "alert_rules"
    __table_args__ = (Index("ix_alert_rules_project", "project_id"),)

    workspace_id: Mapped[uuid.UUID] = mapped_column(
        PGUUID(as_uuid=True), ForeignKey("workspaces.id", ondelete="CASCADE"), nullable=False
    )
    project_id: Mapped[uuid.UUID | None] = mapped_column(
        PGUUID(as_uuid=True), ForeignKey("projects.id", ondelete="CASCADE")
    )
    name: Mapped[str] = mapped_column(String(200), nullable=False)
    is_active: Mapped[bool] = mapped_column(Boolean, default=True, nullable=False)

    # Which change events trigger this rule (HistoryEventType values), and the
    # minimum severity to fire on.
    event_types: Mapped[list[str]] = mapped_column(ARRAY(String), default=list)
    min_severity: Mapped[Severity] = mapped_column(
        pg_enum(Severity, "severity_enum", create_type=False), default=Severity.HIGH
    )
    score_drop_threshold: Mapped[int | None] = mapped_column(Integer)

    channels: Mapped[list[str]] = mapped_column(ARRAY(String), default=list)
    channel_config: Mapped[dict] = mapped_column(JSONB, default=dict)  # encrypted secrets

    # Anti-storm controls (PRD §8.12)
    dedup_window_minutes: Mapped[int] = mapped_column(Integer, default=60, nullable=False)
    quiet_hours: Mapped[dict] = mapped_column(JSONB, default=dict)  # {start,end,tz}
    digest_mode: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)


class Notification(UUIDPrimaryKeyMixin, Base):
    __tablename__ = "notifications"
    __table_args__ = (
        Index("ix_notifications_workspace_created", "workspace_id", "created_at"),
        Index("ix_notifications_recipient_unread", "recipient_user_id", "status"),
        Index("ix_notifications_dedup", "dedup_key"),
    )

    workspace_id: Mapped[uuid.UUID] = mapped_column(
        PGUUID(as_uuid=True), ForeignKey("workspaces.id", ondelete="CASCADE"), nullable=False
    )
    project_id: Mapped[uuid.UUID | None] = mapped_column(PGUUID(as_uuid=True))
    backlink_id: Mapped[uuid.UUID | None] = mapped_column(PGUUID(as_uuid=True))
    alert_rule_id: Mapped[uuid.UUID | None] = mapped_column(
        PGUUID(as_uuid=True), ForeignKey("alert_rules.id", ondelete="SET NULL")
    )
    recipient_user_id: Mapped[uuid.UUID | None] = mapped_column(PGUUID(as_uuid=True))

    channel: Mapped[NotificationChannel] = mapped_column(
        pg_enum(NotificationChannel, "notification_channel_enum"), nullable=False
    )
    status: Mapped[NotificationStatus] = mapped_column(
        pg_enum(NotificationStatus, "notification_status_enum"),
        default=NotificationStatus.PENDING,
        nullable=False,
    )
    severity: Mapped[Severity | None] = mapped_column(
        pg_enum(Severity, "severity_enum", create_type=False)
    )
    title: Mapped[str] = mapped_column(String(400), nullable=False)
    body: Mapped[str | None] = mapped_column(Text)
    payload: Mapped[dict] = mapped_column(JSONB, default=dict)
    dedup_key: Mapped[str | None] = mapped_column(String(200))
    sent_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    read_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    error: Mapped[str | None] = mapped_column(Text)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now(), index=True
    )
