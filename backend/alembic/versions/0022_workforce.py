"""Workforce module tables (Phase 9 P2).

link_type_productivity, user_productivity_overrides, task_assignments (immutable
daily snapshots), working_days, leave_requests. Seeds default productivity for
existing link types (editable guesses — owners to correct in Settings).

Revision ID: 0022_workforce
Revises: 0021_competitor_lifecycle
Create Date: 2026-07-03
"""

from __future__ import annotations

from alembic import op

import app.models  # noqa: F401,E402
from app.models.workforce import (
    LeaveRequest,
    LinkTypeProductivity,
    TaskAssignment,
    UserProductivityOverride,
    WorkingDay,
)

revision = "0022_workforce"
down_revision = "0021_competitor_lifecycle"
branch_labels = None
depends_on = None


def upgrade() -> None:
    bind = op.get_bind()
    for model in (
        LinkTypeProductivity, UserProductivityOverride, TaskAssignment, WorkingDay, LeaveRequest
    ):
        model.__table__.create(bind=bind, checkfirst=True)

    # Seed a default productivity row per existing link type (5/hr placeholder;
    # profiles are famously faster — owners edit real numbers in the UI).
    op.execute(
        """
        INSERT INTO link_type_productivity
            (id, workspace_id, link_type_name, links_per_hour, created_at, updated_at)
        SELECT gen_random_uuid(), workspace_id, name,
               CASE WHEN name ILIKE '%profile%' THEN 30 ELSE 5 END,
               now(), now()
        FROM link_types
        ON CONFLICT (workspace_id, link_type_name) DO NOTHING;
        """
    )


def downgrade() -> None:
    for t in (
        "leave_requests", "working_days", "task_assignments",
        "user_productivity_overrides", "link_type_productivity",
    ):
        op.execute(f"DROP TABLE IF EXISTS {t} CASCADE")
