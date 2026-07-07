"""Duplicate/conflict enterprise schema — richer conflict facts + action log.

Additive only. Extends ``backlink_conflicts`` with human-readable/derived facts
(``reason``, ``similarity``, ``first_member_id``, and distinct-count rollups),
adds two scope/recency composite indexes, and introduces
``backlink_conflict_actions`` — an append-only audit trail of what reviewers did
to a conflict group (acknowledge/resolve/ignore/merge/etc.), workspace-scoped.

Revision ID: 0034_duplicate_enterprise
Revises: 0033_source_domain_rules
Create Date: 2026-07-07
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision = "0034_duplicate_enterprise"  # <=32 chars (alembic_version.version_num is varchar(32))
down_revision = "0033_source_domain_rules"
branch_labels = None
depends_on = None


# New (all-nullable) fact columns on backlink_conflicts.
_NEW_COLUMNS = (
    ("reason", sa.Text()),
    ("similarity", sa.SmallInteger()),
    ("first_member_id", postgresql.UUID(as_uuid=True)),
    ("distinct_projects", sa.SmallInteger()),
    ("distinct_users", sa.SmallInteger()),
    ("distinct_targets", sa.SmallInteger()),
)

_NEW_INDEXES = (
    (
        "ix_backlink_conflicts_ws_scope_status",
        ("workspace_id", "scope", "resolution_status"),
    ),
    ("ix_backlink_conflicts_detected", ("workspace_id", "detected_at")),
)


def upgrade() -> None:
    # ── 1. New fact columns on backlink_conflicts ────────────────────────────
    for name, col_type in _NEW_COLUMNS:
        op.add_column("backlink_conflicts", sa.Column(name, col_type, nullable=True))

    # ── 2. Scope/recency composite indexes ───────────────────────────────────
    for name, cols in _NEW_INDEXES:
        op.create_index(name, "backlink_conflicts", list(cols))

    # ── 3. backlink_conflict_actions audit trail ─────────────────────────────
    op.create_table(
        "backlink_conflict_actions",
        sa.Column(
            "id",
            postgresql.UUID(as_uuid=True),
            primary_key=True,
            server_default=sa.text("gen_random_uuid()"),
        ),
        sa.Column(
            "conflict_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("backlink_conflicts.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("workspace_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("action", sa.String(length=30), nullable=False),
        sa.Column(
            "payload",
            postgresql.JSONB(),
            nullable=False,
            server_default=sa.text("'{}'::jsonb"),
        ),
        sa.Column(
            "actor_user_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("users.id", ondelete="SET NULL"),
            nullable=True,
        ),
        sa.Column("note", sa.Text(), nullable=True),
        # TimestampMixin columns — both must exist so ORM inserts don't fail.
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
    )
    op.create_index(
        "ix_conflict_actions_conflict",
        "backlink_conflict_actions",
        ["conflict_id", "created_at"],
    )
    op.create_index(
        "ix_conflict_actions_workspace",
        "backlink_conflict_actions",
        ["workspace_id", "created_at"],
    )


def downgrade() -> None:
    op.drop_index("ix_conflict_actions_workspace", table_name="backlink_conflict_actions")
    op.drop_index("ix_conflict_actions_conflict", table_name="backlink_conflict_actions")
    op.drop_table("backlink_conflict_actions")

    for name, _cols in _NEW_INDEXES:
        op.drop_index(name, table_name="backlink_conflicts")

    for name, _col_type in reversed(_NEW_COLUMNS):
        op.drop_column("backlink_conflicts", name)
