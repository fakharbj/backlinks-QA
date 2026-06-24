"""Report versioning: version / is_latest / output_target on reports.

Revision ID: 0006_report_versioning
Revises: 0005_index_checks
Create Date: 2026-06-24
"""

from __future__ import annotations

from alembic import op

revision = "0006_report_versioning"
down_revision = "0005_index_checks"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute(
        "ALTER TABLE reports "
        "ADD COLUMN IF NOT EXISTS version integer NOT NULL DEFAULT 1, "
        "ADD COLUMN IF NOT EXISTS is_latest boolean NOT NULL DEFAULT true, "
        "ADD COLUMN IF NOT EXISTS output_target varchar(20) NOT NULL DEFAULT 'download'"
    )
    op.execute(
        "CREATE INDEX IF NOT EXISTS ix_reports_latest "
        "ON reports (workspace_id, report_type) WHERE is_latest"
    )


def downgrade() -> None:
    op.execute("DROP INDEX IF EXISTS ix_reports_latest")
    op.execute(
        "ALTER TABLE reports "
        "DROP COLUMN IF EXISTS output_target, "
        "DROP COLUMN IF EXISTS is_latest, "
        "DROP COLUMN IF EXISTS version"
    )
