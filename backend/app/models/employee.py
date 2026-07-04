"""Employee codes + sheet-user → app-user mappings (Phase 8, feature 3).

The Google sheets carry a free-text "User" label and an "Employee Code" per
backlink. These tables turn those into managed entities:

* ``EmployeeCode`` — the workspace catalog of codes, each optionally linked to a
  real app ``User`` and given a display name; unique per workspace.
* ``UserEmployeeMapping`` — reconciles a raw sheet "User" label to an app user
  (and/or an employee code), so reports can group by real identity.

Both are additive: the free-text ``backlink_records.employee_code`` /
``assigned_user_label`` columns stay the source from the sheet; these add a
managed layer on top.
"""

from __future__ import annotations

import uuid
from datetime import datetime

from sqlalchemy import Boolean, DateTime, ForeignKey, Index, String, UniqueConstraint
from sqlalchemy.dialects.postgresql import UUID as PGUUID
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base, TimestampMixin, UUIDPrimaryKeyMixin


class EmployeeCode(UUIDPrimaryKeyMixin, TimestampMixin, Base):
    __tablename__ = "employee_codes"
    __table_args__ = (
        UniqueConstraint("workspace_id", "code", name="uq_employee_codes_ws_code"),
    )

    workspace_id: Mapped[uuid.UUID] = mapped_column(
        PGUUID(as_uuid=True), ForeignKey("workspaces.id", ondelete="CASCADE"),
        nullable=False, index=True,
    )
    code: Mapped[str] = mapped_column(String(60), nullable=False)
    display_name: Mapped[str | None] = mapped_column(String(200))
    user_id: Mapped[uuid.UUID | None] = mapped_column(
        PGUUID(as_uuid=True), ForeignKey("users.id", ondelete="SET NULL")
    )
    is_active: Mapped[bool] = mapped_column(Boolean, default=True, nullable=False)
    deleted_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    deleted_by: Mapped[uuid.UUID | None] = mapped_column(PGUUID(as_uuid=True))


class UserEmployeeMapping(UUIDPrimaryKeyMixin, TimestampMixin, Base):
    __tablename__ = "user_employee_mappings"
    __table_args__ = (
        UniqueConstraint(
            "workspace_id", "sheet_user_label", name="uq_user_emp_map_ws_label"
        ),
        Index("ix_user_emp_map_workspace", "workspace_id"),
    )

    workspace_id: Mapped[uuid.UUID] = mapped_column(
        PGUUID(as_uuid=True), ForeignKey("workspaces.id", ondelete="CASCADE"), nullable=False
    )
    sheet_user_label: Mapped[str] = mapped_column(String(200), nullable=False)
    user_id: Mapped[uuid.UUID | None] = mapped_column(
        PGUUID(as_uuid=True), ForeignKey("users.id", ondelete="SET NULL")
    )
    employee_code_id: Mapped[uuid.UUID | None] = mapped_column(
        PGUUID(as_uuid=True), ForeignKey("employee_codes.id", ondelete="SET NULL")
    )
    is_current: Mapped[bool] = mapped_column(Boolean, default=True, nullable=False)
    # Laid-off flag (0027): False → excluded from assignment pickers, planner
    # rows and weekly templates. ALL history (links, tasks, reports) is kept.
    is_active: Mapped[bool] = mapped_column(Boolean, default=True, nullable=False)
