"""Company Gmail accounts + assignments (Tranche H).

Additive only — two new tables for tracking which shared company Gmail address
belongs to which user/project (assignment history + a manual last-used signal).
No live Gmail feed. Mirrors the employee-catalog conventions.

Revision ID: 0036_gmail
Revises: 0035_conflict_action_durable
Create Date: 2026-07-07
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision = "0036_gmail"
down_revision = "0035_conflict_action_durable"
branch_labels = None
depends_on = None


def upgrade() -> None:
    bind = op.get_bind()
    insp = sa.inspect(bind)
    tables = set(insp.get_table_names())

    if "gmail_accounts" not in tables:
        op.create_table(
            "gmail_accounts",
            sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True,
                      server_default=sa.text("gen_random_uuid()")),
            sa.Column("workspace_id", postgresql.UUID(as_uuid=True),
                      sa.ForeignKey("workspaces.id", ondelete="CASCADE"), nullable=False),
            sa.Column("email", sa.String(320), nullable=False),
            sa.Column("display_name", sa.String(200)),
            sa.Column("status", sa.String(12), nullable=False, server_default="active"),
            sa.Column("notes", sa.Text()),
            sa.Column("is_active", sa.Boolean(), nullable=False, server_default=sa.true()),
            sa.Column("last_used_at", sa.DateTime(timezone=True)),
            sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
            sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
            sa.UniqueConstraint("workspace_id", "email", name="uq_gmail_accounts_ws_email"),
        )
        op.create_index("ix_gmail_accounts_workspace", "gmail_accounts", ["workspace_id"])

    if "gmail_assignments" not in tables:
        op.create_table(
            "gmail_assignments",
            sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True,
                      server_default=sa.text("gen_random_uuid()")),
            sa.Column("workspace_id", postgresql.UUID(as_uuid=True),
                      sa.ForeignKey("workspaces.id", ondelete="CASCADE"), nullable=False),
            sa.Column("gmail_account_id", postgresql.UUID(as_uuid=True),
                      sa.ForeignKey("gmail_accounts.id", ondelete="CASCADE"), nullable=False),
            sa.Column("scope", sa.String(10), nullable=False),
            sa.Column("user_id", postgresql.UUID(as_uuid=True),
                      sa.ForeignKey("users.id", ondelete="SET NULL")),
            sa.Column("project_id", postgresql.UUID(as_uuid=True),
                      sa.ForeignKey("projects.id", ondelete="CASCADE")),
            sa.Column("assigned_by", postgresql.UUID(as_uuid=True),
                      sa.ForeignKey("users.id", ondelete="SET NULL")),
            sa.Column("assigned_at", sa.DateTime(timezone=True)),
            sa.Column("unassigned_at", sa.DateTime(timezone=True)),
            sa.Column("status", sa.String(10), nullable=False, server_default="active"),
            sa.Column("notes", sa.Text()),
            sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
            sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        )
        op.create_index("ix_gmail_assignments_workspace", "gmail_assignments", ["workspace_id"])
        op.create_index("ix_gmail_assignments_account", "gmail_assignments", ["gmail_account_id", "status"])
        op.create_index("ix_gmail_assignments_user", "gmail_assignments", ["user_id", "status"])
        op.create_index("ix_gmail_assignments_project", "gmail_assignments", ["project_id", "status"])


def downgrade() -> None:
    op.drop_table("gmail_assignments")
    op.drop_table("gmail_accounts")
