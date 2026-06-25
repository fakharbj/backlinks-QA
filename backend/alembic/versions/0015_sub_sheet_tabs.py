"""Google-Sheet sub-sheet (tab) sync (Phase 8, features 5/6).

Adds ``google_sheet_project_tabs`` (one row per detected tab), ``imports.sheet_tab``,
and ``backlink_records.sheet_tab``; widens the per-sheet-row idempotency index to
include the tab so the same row number in different tabs no longer collides.
Additive + idempotent.

Revision ID: 0015_sub_sheet_tabs
Revises: 0014_link_types
Create Date: 2026-06-26
"""

from __future__ import annotations

from alembic import op

# Register models on Base.metadata.
import app.models  # noqa: F401,E402
from app.models.sheet_tab import GoogleSheetTab

revision = "0015_sub_sheet_tabs"
down_revision = "0014_link_types"
branch_labels = None
depends_on = None


def upgrade() -> None:
    bind = op.get_bind()
    GoogleSheetTab.__table__.create(bind=bind, checkfirst=True)
    op.execute("ALTER TABLE imports ADD COLUMN IF NOT EXISTS sheet_tab varchar(200)")
    op.execute("ALTER TABLE backlink_records ADD COLUMN IF NOT EXISTS sheet_tab varchar(200)")
    # Widen the same-entry idempotency key to include the tab.
    op.execute("DROP INDEX IF EXISTS uq_backlink_records_sheet_entry")
    op.execute(
        "CREATE UNIQUE INDEX IF NOT EXISTS uq_backlink_records_sheet_entry "
        "ON backlink_records (source_sheet_id, sheet_tab, sheet_row_ref) "
        "WHERE source_sheet_id IS NOT NULL"
    )


def downgrade() -> None:
    op.execute("DROP INDEX IF EXISTS uq_backlink_records_sheet_entry")
    op.execute(
        "CREATE UNIQUE INDEX IF NOT EXISTS uq_backlink_records_sheet_entry "
        "ON backlink_records (source_sheet_id, sheet_row_ref) "
        "WHERE source_sheet_id IS NOT NULL"
    )
    op.execute("ALTER TABLE backlink_records DROP COLUMN IF EXISTS sheet_tab")
    op.execute("ALTER TABLE imports DROP COLUMN IF EXISTS sheet_tab")
    op.execute("DROP TABLE IF EXISTS google_sheet_project_tabs CASCADE;")
