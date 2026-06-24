"""Link identity + assignment history (Phase 3).

A ``LinkIdentity`` is the canonical identity of a backlink within a workspace,
defined by ``(source_url_normalized, target_domain)`` (the locked duplicate rule).
Many ``backlink_records`` can map to one identity — across projects, users, or
different target URLs on the same domain — which is exactly how duplicates are
detected. The identity is keyed by a sha256 ``identity_key`` so the unique index
stays small and fast even for very long source URLs.

``AssignmentHistory`` records every change of a link's assigned user/employee, so
"who owned this link, and when did it change" is auditable.
"""

from __future__ import annotations

import uuid
from datetime import datetime

from sqlalchemy import DateTime, ForeignKey, Index, Integer, String, Text, func
from sqlalchemy.dialects.postgresql import UUID as PGUUID
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base, TimestampMixin, UUIDPrimaryKeyMixin


class LinkIdentity(UUIDPrimaryKeyMixin, TimestampMixin, Base):
    __tablename__ = "link_identity"
    __table_args__ = (
        Index("ux_link_identity_key", "identity_key", unique=True),
        Index("ix_link_identity_workspace_source", "workspace_id", "source_url_normalized"),
    )

    workspace_id: Mapped[uuid.UUID] = mapped_column(
        PGUUID(as_uuid=True), ForeignKey("workspaces.id", ondelete="CASCADE"), nullable=False
    )
    # sha256("{workspace}|{source_url_normalized}|{target_domain}") — the unique key.
    identity_key: Mapped[str] = mapped_column(String(64), nullable=False)
    source_url_normalized: Mapped[str] = mapped_column(Text, nullable=False)
    target_domain: Mapped[str] = mapped_column(String(255), nullable=False, default="")

    # Rollups recomputed when any mapped backlink changes.
    occurrence_count: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    project_count: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    user_count: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    target_url_count: Mapped[int] = mapped_column(Integer, default=0, nullable=False)

    first_seen_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    last_seen_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))


class AssignmentHistory(UUIDPrimaryKeyMixin, Base):
    __tablename__ = "assignment_history"
    __table_args__ = (
        Index("ix_assignment_history_backlink", "backlink_id", "changed_at"),
        Index("ix_assignment_history_workspace", "workspace_id", "changed_at"),
    )

    workspace_id: Mapped[uuid.UUID] = mapped_column(PGUUID(as_uuid=True), nullable=False)
    project_id: Mapped[uuid.UUID | None] = mapped_column(PGUUID(as_uuid=True))
    backlink_id: Mapped[uuid.UUID] = mapped_column(PGUUID(as_uuid=True), nullable=False)
    link_identity_id: Mapped[uuid.UUID | None] = mapped_column(PGUUID(as_uuid=True))

    old_user_label: Mapped[str | None] = mapped_column(String(200))
    new_user_label: Mapped[str | None] = mapped_column(String(200))
    source: Mapped[str] = mapped_column(String(20), default="sheet")  # sheet | ui
    changed_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )
