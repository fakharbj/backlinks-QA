"""Company Gmail accounts + their assignments to people/projects (Tranche H).

The agency hands out shared company Gmail addresses for outreach; owners need to
see which address belongs to which employee and/or project, when it was handed
over and by whom, and whether it is still active. There is NO Google OAuth here —
this is a managed **assignment + light usage-metadata** layer, mirroring the
``employee.py`` catalog conventions (plain-string status like ``batch`` /
``source_domain.origin``, app-level validation, workspace-scoped).

* ``GmailAccount`` — the workspace catalog of addresses (one row per address).
* ``GmailAssignment`` — append-only history: who/what an address is handed to.
  Reassigning closes the prior active row (``unassigned_at``) and opens a new one,
  so the table doubles as the activity log (never hard-deleted).
"""

from __future__ import annotations

import uuid
from datetime import datetime

from sqlalchemy import (
    Boolean,
    DateTime,
    ForeignKey,
    Index,
    String,
    Text,
    UniqueConstraint,
)
from sqlalchemy.dialects.postgresql import UUID as PGUUID
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base, TimestampMixin, UUIDPrimaryKeyMixin

# Plain-string vocabularies (validated in the service; matches batch/source_domain).
GMAIL_ACCOUNT_STATUSES = ("active", "suspended", "retired")
GMAIL_SCOPES = ("user", "project")
GMAIL_ASSIGNMENT_STATUSES = ("active", "revoked")


class GmailAccount(UUIDPrimaryKeyMixin, TimestampMixin, Base):
    __tablename__ = "gmail_accounts"
    __table_args__ = (
        # Email is stored lowercased by the service → a plain unique works.
        UniqueConstraint("workspace_id", "email", name="uq_gmail_accounts_ws_email"),
        Index("ix_gmail_accounts_workspace", "workspace_id"),
    )

    workspace_id: Mapped[uuid.UUID] = mapped_column(
        PGUUID(as_uuid=True), ForeignKey("workspaces.id", ondelete="CASCADE"),
        nullable=False, index=True,
    )
    email: Mapped[str] = mapped_column(String(320), nullable=False)
    display_name: Mapped[str | None] = mapped_column(String(200))
    # active | suspended | retired
    status: Mapped[str] = mapped_column(String(12), default="active", nullable=False)
    notes: Mapped[str | None] = mapped_column(Text)
    is_active: Mapped[bool] = mapped_column(Boolean, default=True, nullable=False)
    # Light usage signal (manual — there is no live Gmail feed).
    last_used_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))


class GmailAssignment(UUIDPrimaryKeyMixin, TimestampMixin, Base):
    __tablename__ = "gmail_assignments"
    __table_args__ = (
        Index("ix_gmail_assignments_workspace", "workspace_id"),
        Index("ix_gmail_assignments_account", "gmail_account_id", "status"),
        Index("ix_gmail_assignments_user", "user_id", "status"),
        Index("ix_gmail_assignments_project", "project_id", "status"),
    )

    workspace_id: Mapped[uuid.UUID] = mapped_column(
        PGUUID(as_uuid=True), ForeignKey("workspaces.id", ondelete="CASCADE"),
        nullable=False, index=True,
    )
    gmail_account_id: Mapped[uuid.UUID] = mapped_column(
        PGUUID(as_uuid=True), ForeignKey("gmail_accounts.id", ondelete="CASCADE"), nullable=False
    )
    # user | project
    scope: Mapped[str] = mapped_column(String(10), nullable=False)
    # Exactly one of these is set (per scope) — service enforces it.
    user_id: Mapped[uuid.UUID | None] = mapped_column(
        PGUUID(as_uuid=True), ForeignKey("users.id", ondelete="SET NULL")
    )
    project_id: Mapped[uuid.UUID | None] = mapped_column(
        PGUUID(as_uuid=True), ForeignKey("projects.id", ondelete="CASCADE")
    )
    assigned_by: Mapped[uuid.UUID | None] = mapped_column(
        PGUUID(as_uuid=True), ForeignKey("users.id", ondelete="SET NULL")
    )
    assigned_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    unassigned_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    # active | revoked
    status: Mapped[str] = mapped_column(String(10), default="active", nullable=False)
    notes: Mapped[str | None] = mapped_column(Text)
