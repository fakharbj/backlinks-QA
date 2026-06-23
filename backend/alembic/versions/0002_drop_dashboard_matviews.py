"""Drop the dead dashboard materialized views.

The dashboard was rewritten to query ``backlink_records`` live (always fresh, no
refresh lag), so ``mv_project_dashboard`` / ``mv_vendor_failure_rates`` /
``mv_domain_failures`` are no longer read by anything. Keeping them only cost
storage and a periodic full REFRESH (heavy at 1M+ rows). This migration drops
them; the downgrade recreates them for a clean rollback.

Revision ID: 0002_drop_dashboard_matviews
Revises: 0001_initial
Create Date: 2026-06-24
"""

from __future__ import annotations

from alembic import op

from app.db import ddl

revision = "0002_drop_dashboard_matviews"
down_revision = "0001_initial"
branch_labels = None
depends_on = None


def upgrade() -> None:
    for name in ddl.MATVIEW_NAMES:
        op.execute(f"DROP MATERIALIZED VIEW IF EXISTS {name} CASCADE;")


def downgrade() -> None:
    # Recreate the views exactly as 0001 defined them (statement-by-statement).
    for stmt in (s.strip() for s in ddl.MATVIEWS_SQL.split(";")):
        if stmt:
            op.execute(stmt)
