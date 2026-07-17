"""Skips are not errors (owner rule).

Spacer/heading rows without a source URL are NORMAL sheet formatting — they
must not turn a sync "Partly failed" or appear as row errors. New row status
'skipped' + an imports.skipped_rows counter so skips are visible (green) but
never counted against the sync.

Revision ID: 0050_skipped_rows
Revises: 0049_qa_test_submission_fields
Create Date: 2026-07-18
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op

revision = "0050_skipped_rows"
down_revision = "0049_qa_test_submission_fields"
branch_labels = None
depends_on = None


def upgrade() -> None:
    bind = op.get_bind()
    # New enum value (PG12+ allows ADD VALUE in a transaction as long as it
    # isn't USED in the same transaction — we only add it here).
    op.execute("ALTER TYPE import_row_status_enum ADD VALUE IF NOT EXISTS 'skipped'")
    has_col = bind.execute(
        sa.text(
            "SELECT 1 FROM information_schema.columns "
            "WHERE table_name='imports' AND column_name='skipped_rows'"
        )
    ).first()
    if not has_col:
        op.execute("ALTER TABLE imports ADD COLUMN skipped_rows INTEGER NOT NULL DEFAULT 0")


def downgrade() -> None:
    # Enum values can't be removed in PG; only drop the counter column.
    op.execute("ALTER TABLE imports DROP COLUMN IF EXISTS skipped_rows")
