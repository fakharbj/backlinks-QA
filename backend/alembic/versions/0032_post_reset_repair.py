"""Restore raw-SQL-only columns that a create_all rebuild (factory reset) omits.

Migration 0001 builds the schema from ``Base.metadata.create_all``; columns that
earlier migrations added via raw ``ALTER TABLE`` (and were NOT mapped on the ORM
models) are therefore absent after a from-scratch create_all rebuild. This
migration idempotently restores them so a reset schema matches the full chain:

* ``competitor_source_domains.da`` / ``.pa`` (from 0024) — actively joined as
  ``coalesce(d.da, sd.da)`` by competitor queries; their absence 500s the
  Competitor desk. (Now also mapped on the model to prevent recurrence.)
* ``backlink_records.batch_id`` / ``crawl_results.batch_id`` /
  ``backlink_history.batch_id`` (from 0020) — legacy batch-tracking columns,
  currently unreferenced but restored for schema fidelity.

All statements use IF NOT EXISTS, so this is a safe no-op on databases that were
migrated incrementally and already have the columns.

Revision ID: 0032_post_reset_repair
Revises: 0031_date_types
Create Date: 2026-07-07
"""

from __future__ import annotations

from alembic import op

revision = "0032_post_reset_repair"
down_revision = "0031_date_types"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute("ALTER TABLE competitor_source_domains ADD COLUMN IF NOT EXISTS da integer")
    op.execute("ALTER TABLE competitor_source_domains ADD COLUMN IF NOT EXISTS pa integer")
    op.execute("ALTER TABLE backlink_records ADD COLUMN IF NOT EXISTS batch_id uuid")
    op.execute("ALTER TABLE crawl_results ADD COLUMN IF NOT EXISTS batch_id uuid")
    op.execute("ALTER TABLE backlink_history ADD COLUMN IF NOT EXISTS batch_id uuid")


def downgrade() -> None:
    # Symmetric drop; the columns are re-added by 0020/0024 on a full chain.
    op.execute("ALTER TABLE backlink_history DROP COLUMN IF EXISTS batch_id")
    op.execute("ALTER TABLE crawl_results DROP COLUMN IF EXISTS batch_id")
    op.execute("ALTER TABLE backlink_records DROP COLUMN IF EXISTS batch_id")
    op.execute("ALTER TABLE competitor_source_domains DROP COLUMN IF EXISTS pa")
    op.execute("ALTER TABLE competitor_source_domains DROP COLUMN IF EXISTS da")
