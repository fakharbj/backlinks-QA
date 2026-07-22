"""Intern user level (owner final brief #7): add 'intern' to the native
role_enum. Interns submit links into isolated review batches (never straight
into production), see only their own work, and are promoted via a normal role
change. Permissions live in code (rbac._MATRIX); fresh installs pick the value
up from the Python enum automatically.

Revision ID: 0057_intern_role
Revises: 0056_scoring_v3_zero_canonical
"""

from __future__ import annotations

from alembic import op

revision = "0057_intern_role"
down_revision = "0056_scoring_v3_zero_canonical"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute("ALTER TYPE role_enum ADD VALUE IF NOT EXISTS 'intern'")


def downgrade() -> None:
    # Postgres can't remove an enum value; harmless to leave in place.
    pass
