"""Performance indexes for the user-dashboard / performance queries.

The "new source domain" counts (user dashboard, performance, day-report) test, for
each row, whether an EARLIER backlink exists from the same domain. Without a
covering index that turned into a per-row BitmapAnd over the whole workspace
(~380ms for one heavy user, all-time). These covering + expression indexes make
each check an index-only scan and let per-user filtering use the lowercased label:

  ix_blr_ws_userlower  (workspace_id, lower(assigned_user_label))
  ix_blr_ws_domain     (workspace_id, source_domain) INCLUDE (placement_date, created_at, id)
  ix_blr_proj_domain   (project_id, source_domain)   INCLUDE (placement_date, created_at, id)

Measured: the heavy user-dashboard stat query dropped 386ms -> 30ms; the full
all-time dashboard endpoint ~120ms. Idempotent (IF NOT EXISTS).

Revision ID: 0040_perf_indexes
Revises: 0039_backfill_placement2
Create Date: 2026-07-07
"""

from __future__ import annotations

from alembic import op

revision = "0040_perf_indexes"
down_revision = "0039_backfill_placement2"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute(
        "CREATE INDEX IF NOT EXISTS ix_blr_ws_userlower "
        "ON backlink_records (workspace_id, lower(assigned_user_label))"
    )
    op.execute(
        "CREATE INDEX IF NOT EXISTS ix_blr_ws_domain "
        "ON backlink_records (workspace_id, source_domain) "
        "INCLUDE (placement_date, created_at, id)"
    )
    op.execute(
        "CREATE INDEX IF NOT EXISTS ix_blr_proj_domain "
        "ON backlink_records (project_id, source_domain) "
        "INCLUDE (placement_date, created_at, id)"
    )


def downgrade() -> None:
    op.execute("DROP INDEX IF EXISTS ix_blr_ws_userlower")
    op.execute("DROP INDEX IF EXISTS ix_blr_ws_domain")
    op.execute("DROP INDEX IF EXISTS ix_blr_proj_domain")
