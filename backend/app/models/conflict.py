"""Backlink duplicate / conflict groups (Phase 8, feature 9).

A conflict groups every backlink that shares the same canonical source URL
(``canonical_url_id``) within a workspace — i.e. the same page reached through
cosmetically-different URLs, or the same page linked from multiple projects/users.
``scope`` records the relationship; ``resolution_status`` tracks the review
lifecycle. Members are the individual backlinks in the group.

Detection is fingerprint-driven (an indexed ``canonical_url_id`` lookup), so it
scales without scanning. Workspace-scoped so tenants never see each other's groups.
"""

from __future__ import annotations

import uuid
from datetime import datetime

from sqlalchemy import (
    DateTime,
    ForeignKey,
    Index,
    Integer,
    SmallInteger,
    String,
    Text,
    UniqueConstraint,
)
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.dialects.postgresql import UUID as PGUUID
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base, TimestampMixin, UUIDPrimaryKeyMixin


class BacklinkConflict(UUIDPrimaryKeyMixin, TimestampMixin, Base):
    __tablename__ = "backlink_conflicts"
    __table_args__ = (
        # One group per (workspace, canonical source URL).
        UniqueConstraint(
            "workspace_id", "canonical_url_id", name="uq_backlink_conflicts_ws_canonical"
        ),
        Index("ix_backlink_conflicts_workspace_status", "workspace_id", "resolution_status"),
        Index("ix_backlink_conflicts_canonical", "canonical_url_id"),
        Index(
            "ix_backlink_conflicts_ws_scope_status",
            "workspace_id",
            "scope",
            "resolution_status",
        ),
        Index("ix_backlink_conflicts_detected", "workspace_id", "detected_at"),
    )

    workspace_id: Mapped[uuid.UUID] = mapped_column(
        PGUUID(as_uuid=True), ForeignKey("workspaces.id", ondelete="CASCADE"), nullable=False
    )
    canonical_url_id: Mapped[uuid.UUID] = mapped_column(PGUUID(as_uuid=True), nullable=False)
    # Set when every member is in one project; NULL when the group spans projects.
    project_id: Mapped[uuid.UUID | None] = mapped_column(PGUUID(as_uuid=True))
    # same_project | cross_project | cross_user | competitor_vs_project
    scope: Mapped[str] = mapped_column(String(40), nullable=False)
    # open | acknowledged | resolved | ignored
    resolution_status: Mapped[str] = mapped_column(String(20), default="open", nullable=False)
    member_count: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    detected_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    resolved_by: Mapped[uuid.UUID | None] = mapped_column(
        PGUUID(as_uuid=True), ForeignKey("users.id", ondelete="SET NULL")
    )
    resolved_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    # ── Enterprise fact columns (all nullable; see migration 0034) ───────────
    # Human-readable/derived explanation of why the group is a conflict.
    reason: Mapped[str | None] = mapped_column(Text)
    # 0-100 similarity of the members (NULL when not computed).
    similarity: Mapped[int | None] = mapped_column(SmallInteger)
    # The earliest/reference backlink in the group.
    first_member_id: Mapped[uuid.UUID | None] = mapped_column(PGUUID(as_uuid=True))
    # Distinct-count rollups across the group's members.
    distinct_projects: Mapped[int | None] = mapped_column(SmallInteger)
    distinct_users: Mapped[int | None] = mapped_column(SmallInteger)
    distinct_targets: Mapped[int | None] = mapped_column(SmallInteger)


class BacklinkConflictMember(UUIDPrimaryKeyMixin, TimestampMixin, Base):
    __tablename__ = "backlink_conflict_members"
    __table_args__ = (
        UniqueConstraint(
            "conflict_id", "backlink_id", name="uq_conflict_members_conflict_backlink"
        ),
        Index("ix_conflict_members_conflict", "conflict_id"),
        Index("ix_conflict_members_backlink", "backlink_id"),
    )

    conflict_id: Mapped[uuid.UUID] = mapped_column(
        PGUUID(as_uuid=True),
        ForeignKey("backlink_conflicts.id", ondelete="CASCADE"),
        nullable=False,
    )
    backlink_id: Mapped[uuid.UUID] = mapped_column(PGUUID(as_uuid=True), nullable=False)


class BacklinkConflictAction(UUIDPrimaryKeyMixin, TimestampMixin, Base):
    """Append-only audit trail of reviewer actions on a conflict group.

    One row per action (acknowledge / resolve / ignore / merge / etc.).
    Workspace-scoped so tenants never see each other's history.
    """

    __tablename__ = "backlink_conflict_actions"
    __table_args__ = (
        Index("ix_conflict_actions_conflict", "conflict_id", "created_at"),
        Index("ix_conflict_actions_workspace", "workspace_id", "created_at"),
    )

    # No FK to backlink_conflicts: this is an append-only AUDIT log that must
    # OUTLIVE the group (keep-one/bulk can delete the group; its history stays).
    conflict_id: Mapped[uuid.UUID] = mapped_column(PGUUID(as_uuid=True), nullable=False)
    workspace_id: Mapped[uuid.UUID] = mapped_column(PGUUID(as_uuid=True), nullable=False)
    # acknowledge | resolve | ignore | reopen | merge | ...
    action: Mapped[str] = mapped_column(String(30), nullable=False)
    payload: Mapped[dict] = mapped_column(JSONB, default=dict, nullable=False)
    actor_user_id: Mapped[uuid.UUID | None] = mapped_column(
        PGUUID(as_uuid=True), ForeignKey("users.id", ondelete="SET NULL")
    )
    note: Mapped[str | None] = mapped_column(Text)
