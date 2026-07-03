"""Project×link-type scoring scope + competitor domain metrics (final gaps).

* ``scoring_rule_versions.link_type_id`` — enables the ``project_link_type``
  scope: one project's points for one link type (most specific in the chain).
* ``competitor_source_domains.da/pa`` — checked metrics for opportunity domains
  (filled cache-first by the competitor metrics check; rebuilt rows re-fill from
  the Redis cache at zero API cost).

Revision ID: 0024_project_linktype_scoring
Revises: 0023_teamlead_users
Create Date: 2026-07-03
"""

from __future__ import annotations

from alembic import op

revision = "0024_project_linktype_scoring"
down_revision = "0023_teamlead_users"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute(
        "ALTER TABLE scoring_rule_versions ADD COLUMN IF NOT EXISTS link_type_id uuid"
    )
    op.execute(
        "CREATE INDEX IF NOT EXISTS ix_scoring_rule_versions_lt "
        "ON scoring_rule_versions (workspace_id, scope, scope_ref_id, link_type_id, is_latest)"
    )
    op.execute("ALTER TABLE competitor_source_domains ADD COLUMN IF NOT EXISTS da integer")
    op.execute("ALTER TABLE competitor_source_domains ADD COLUMN IF NOT EXISTS pa integer")


def downgrade() -> None:
    op.execute("ALTER TABLE competitor_source_domains DROP COLUMN IF EXISTS pa")
    op.execute("ALTER TABLE competitor_source_domains DROP COLUMN IF EXISTS da")
    op.execute("DROP INDEX IF EXISTS ix_scoring_rule_versions_lt")
    op.execute("ALTER TABLE scoring_rule_versions DROP COLUMN IF EXISTS link_type_id")
