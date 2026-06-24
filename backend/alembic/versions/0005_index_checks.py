"""Index checking: index_checks table + index columns on backlink_records.

Revision ID: 0005_index_checks
Revises: 0004_link_identity_duplicates
Create Date: 2026-06-24
"""

from __future__ import annotations

from alembic import op

import app.models  # noqa: F401,E402
from app.models.index_check import IndexCheck

revision = "0005_index_checks"
down_revision = "0004_link_identity_duplicates"
branch_labels = None
depends_on = None


def upgrade() -> None:
    bind = op.get_bind()
    IndexCheck.__table__.create(bind=bind, checkfirst=True)

    op.execute(
        "ALTER TABLE backlink_records "
        "ADD COLUMN IF NOT EXISTS index_status varchar(20), "
        "ADD COLUMN IF NOT EXISTS index_result_count integer, "
        "ADD COLUMN IF NOT EXISTS index_checked_at timestamptz"
    )
    op.execute(
        "CREATE INDEX IF NOT EXISTS ix_backlink_records_index_status "
        "ON backlink_records (workspace_id, index_status)"
    )
    op.execute(
        "CREATE INDEX IF NOT EXISTS ix_backlink_records_index_due "
        "ON backlink_records (index_checked_at)"
    )


def downgrade() -> None:
    op.execute("DROP INDEX IF EXISTS ix_backlink_records_index_due")
    op.execute("DROP INDEX IF EXISTS ix_backlink_records_index_status")
    op.execute(
        "ALTER TABLE backlink_records "
        "DROP COLUMN IF EXISTS index_checked_at, "
        "DROP COLUMN IF EXISTS index_result_count, "
        "DROP COLUMN IF EXISTS index_status"
    )
    op.execute("DROP TABLE IF EXISTS index_checks CASCADE;")
