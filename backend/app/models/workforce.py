"""Workforce module (Phase 9 P2): task assignments, productivity, calendar, leave.

Owner model: day → user → projects → hours → link types → expected links.
``TaskAssignment`` rows are the **immutable daily snapshot** — performance for a
date is always computed against that date's rows, so changing tomorrow's plan
never rewrites yesterday's accountability. Users are identified by their sheet
``user_label`` (the same attribution the backlink data actually carries; the
Employees desk maps labels to app accounts).
"""

from __future__ import annotations

import uuid
from datetime import date, datetime

from sqlalchemy import Boolean, Date, DateTime, Index, Integer, Numeric, String, UniqueConstraint
from sqlalchemy.dialects.postgresql import ARRAY
from sqlalchemy.dialects.postgresql import UUID as PGUUID
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base, TimestampMixin, UUIDPrimaryKeyMixin


class LinkTypeProductivity(UUIDPrimaryKeyMixin, TimestampMixin, Base):
    """How many links of a type one person produces per hour (workspace default)."""

    __tablename__ = "link_type_productivity"
    __table_args__ = (
        UniqueConstraint("workspace_id", "link_type_name", name="uq_ltp_ws_type"),
    )

    workspace_id: Mapped[uuid.UUID] = mapped_column(PGUUID(as_uuid=True), nullable=False)
    link_type_name: Mapped[str] = mapped_column(String(80), nullable=False)
    links_per_hour: Mapped[float] = mapped_column(Numeric(6, 2), nullable=False, default=5)


class UserProductivityOverride(UUIDPrimaryKeyMixin, TimestampMixin, Base):
    """Per-user override of a link type's links-per-hour (falls back to global)."""

    __tablename__ = "user_productivity_overrides"
    __table_args__ = (
        UniqueConstraint(
            "workspace_id", "user_label", "link_type_name", name="uq_upo_ws_user_type"
        ),
    )

    workspace_id: Mapped[uuid.UUID] = mapped_column(PGUUID(as_uuid=True), nullable=False)
    user_label: Mapped[str] = mapped_column(String(200), nullable=False)
    link_type_name: Mapped[str] = mapped_column(String(80), nullable=False)
    links_per_hour: Mapped[float] = mapped_column(Numeric(6, 2), nullable=False)


class TaskAssignment(UUIDPrimaryKeyMixin, TimestampMixin, Base):
    """One user's plan for one project on one day (the immutable snapshot)."""

    __tablename__ = "task_assignments"
    __table_args__ = (
        UniqueConstraint(
            "workspace_id", "project_id", "user_label", "day", name="uq_task_ws_proj_user_day"
        ),
        Index("ix_task_assignments_day", "workspace_id", "day"),
        Index("ix_task_assignments_user", "workspace_id", "user_label", "day"),
    )

    workspace_id: Mapped[uuid.UUID] = mapped_column(PGUUID(as_uuid=True), nullable=False)
    project_id: Mapped[uuid.UUID] = mapped_column(PGUUID(as_uuid=True), nullable=False)
    user_label: Mapped[str] = mapped_column(String(200), nullable=False)
    day: Mapped[date] = mapped_column(Date, nullable=False)
    hours: Mapped[float] = mapped_column(Numeric(4, 1), nullable=False, default=0)
    link_type_names: Mapped[list[str]] = mapped_column(ARRAY(String), default=list)
    expected_links: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    note: Mapped[str | None] = mapped_column(String(300))
    created_by: Mapped[uuid.UUID | None] = mapped_column(PGUUID(as_uuid=True))


class WorkingDay(UUIDPrimaryKeyMixin, Base):
    """Company calendar override for one date. No row = the default rule
    (Mon–Sat working, Sunday off)."""

    __tablename__ = "working_days"
    __table_args__ = (UniqueConstraint("workspace_id", "day", name="uq_working_day"),)

    workspace_id: Mapped[uuid.UUID] = mapped_column(PGUUID(as_uuid=True), nullable=False)
    day: Mapped[date] = mapped_column(Date, nullable=False)
    is_working: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)


class TeamLeadAssignment(UUIDPrimaryKeyMixin, TimestampMixin, Base):
    """Which team members (by sheet user label) a TeamLead/manager oversees.

    When a manager has assignments, people-facing views (performance, day
    reports, leave lists) are restricted to those labels; admins and managers
    without assignments see everything (backward-compatible default).
    """

    __tablename__ = "teamlead_users"
    __table_args__ = (
        UniqueConstraint(
            "workspace_id", "manager_user_id", "member_label", name="uq_teamlead_member"
        ),
        Index("ix_teamlead_users_manager", "workspace_id", "manager_user_id"),
    )

    workspace_id: Mapped[uuid.UUID] = mapped_column(PGUUID(as_uuid=True), nullable=False)
    manager_user_id: Mapped[uuid.UUID] = mapped_column(PGUUID(as_uuid=True), nullable=False)
    member_label: Mapped[str] = mapped_column(String(200), nullable=False)


class LeaveRequest(UUIDPrimaryKeyMixin, TimestampMixin, Base):
    __tablename__ = "leave_requests"
    __table_args__ = (Index("ix_leave_requests_ws_status", "workspace_id", "status"),)

    workspace_id: Mapped[uuid.UUID] = mapped_column(PGUUID(as_uuid=True), nullable=False)
    user_label: Mapped[str] = mapped_column(String(200), nullable=False)
    start_date: Mapped[date] = mapped_column(Date, nullable=False)
    end_date: Mapped[date] = mapped_column(Date, nullable=False)
    reason: Mapped[str | None] = mapped_column(String(300))
    # pending | approved | rejected. Approved leave excuses that day's tasks;
    # rejected keeps the requirement accountable.
    status: Mapped[str] = mapped_column(String(12), nullable=False, default="pending")
    requested_by: Mapped[uuid.UUID | None] = mapped_column(PGUUID(as_uuid=True))
    decided_by: Mapped[uuid.UUID | None] = mapped_column(PGUUID(as_uuid=True))
    decided_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
