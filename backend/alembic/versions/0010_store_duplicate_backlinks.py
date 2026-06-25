"""Stop skipping duplicate backlinks (Phase 8, feature 10).

Drops the in-project ``(source, target)`` uniqueness so a sheet can contain the
same link twice and **both** rows are stored (then grouped by canonical fingerprint
into a conflict). Adds a partial unique index on ``(source_sheet_id, sheet_row_ref)``
so a re-sync still updates the **same sheet row** in place (idempotent) rather than
multiplying rows.

Reversible, but ``downgrade`` will fail if duplicate (project, source, target) rows
exist by then — expected once duplicates are intentionally stored.

Revision ID: 0010_store_duplicate_backlinks
Revises: 0009_project_settings_domains
Create Date: 2026-06-26
"""

from __future__ import annotations

from alembic import op

# Register models on Base.metadata.
import app.models  # noqa: F401,E402

revision = "0010_store_duplicate_backlinks"
down_revision = "0009_project_settings_domains"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute(
        "ALTER TABLE backlink_records DROP CONSTRAINT IF EXISTS uq_backlink_records_project_src_tgt;"
    )
    op.execute(
        "CREATE UNIQUE INDEX IF NOT EXISTS uq_backlink_records_sheet_entry "
        "ON backlink_records (source_sheet_id, sheet_row_ref) WHERE source_sheet_id IS NOT NULL;"
    )


def downgrade() -> None:
    op.execute("DROP INDEX IF EXISTS uq_backlink_records_sheet_entry;")
    op.execute(
        "ALTER TABLE backlink_records ADD CONSTRAINT uq_backlink_records_project_src_tgt "
        "UNIQUE (project_id, source_url_normalized, target_url_normalized);"
    )
