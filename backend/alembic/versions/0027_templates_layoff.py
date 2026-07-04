"""Weekly assignment templates + employee laid-off flag.

* ``task_week_templates`` — the standing weekly plan: one row per
  (person, weekday, project). "Set the week up once" — applying a week copies
  these into real ``task_assignments`` (idempotent upsert), and a weekly beat
  job materializes the NEXT week automatically.
* ``user_employee_mappings.is_active`` — laid-off people are excluded from
  assignment pickers, the planner and templates, while ALL their history stays.

Revision ID: 0027_templates_layoff
Revises: 0026_finalization_columns
Create Date: 2026-07-05
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects.postgresql import ARRAY, UUID

revision = "0027_templates_layoff"
down_revision = "0026_finalization_columns"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "task_week_templates",
        sa.Column("id", UUID(as_uuid=True), primary_key=True),
        sa.Column("workspace_id", UUID(as_uuid=True), nullable=False),
        sa.Column("user_label", sa.String(200), nullable=False),
        sa.Column("weekday", sa.Integer(), nullable=False),  # 0=Mon … 6=Sun
        sa.Column("project_id", UUID(as_uuid=True), nullable=False),
        sa.Column("hours", sa.Numeric(4, 1), nullable=False, server_default="0"),
        sa.Column("link_type_names", ARRAY(sa.String()), nullable=True),
        sa.Column("priority", sa.String(10), nullable=True),
        sa.Column("note", sa.String(300), nullable=True),
        sa.Column("created_by", UUID(as_uuid=True), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.UniqueConstraint(
            "workspace_id", "user_label", "weekday", "project_id",
            name="uq_task_template_ws_user_day_proj",
        ),
    )
    op.create_index(
        "ix_task_week_templates_ws", "task_week_templates", ["workspace_id", "user_label"]
    )

    op.add_column(
        "user_employee_mappings",
        sa.Column("is_active", sa.Boolean(), nullable=False, server_default="true"),
    )


def downgrade() -> None:
    op.drop_column("user_employee_mappings", "is_active")
    op.drop_index("ix_task_week_templates_ws", table_name="task_week_templates")
    op.drop_table("task_week_templates")
