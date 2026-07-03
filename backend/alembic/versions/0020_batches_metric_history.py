"""Unified batch registry + metric check history (Phase 9 P0).

Adds ``batches`` + ``batch_logs`` (operations layer over all runners) and
``metric_check_history`` (freshness/audit). Adds nullable ``batch_id`` to
``imports``, ``crawl_jobs`` and ``reports`` so existing runner rows link back to
their batch. Additive + idempotent; no behavioral change on deploy.

Revision ID: 0020_batches_metric_history
Revises: 0019_competitor_engine
Create Date: 2026-07-02
"""

from __future__ import annotations

from alembic import op

import app.models  # noqa: F401,E402
from app.models.batch import Batch, BatchLog
from app.models.metric_history import MetricCheckHistory

revision = "0020_batches_metric_history"
down_revision = "0019_competitor_engine"
branch_labels = None
depends_on = None


def upgrade() -> None:
    bind = op.get_bind()
    Batch.__table__.create(bind=bind, checkfirst=True)
    BatchLog.__table__.create(bind=bind, checkfirst=True)
    MetricCheckHistory.__table__.create(bind=bind, checkfirst=True)
    for table in ("imports", "crawl_jobs", "reports"):
        op.execute(f"ALTER TABLE {table} ADD COLUMN IF NOT EXISTS batch_id uuid")
        op.execute(
            f"CREATE INDEX IF NOT EXISTS ix_{table}_batch_id ON {table} (batch_id)"
        )


def downgrade() -> None:
    for table in ("imports", "crawl_jobs", "reports"):
        op.execute(f"DROP INDEX IF EXISTS ix_{table}_batch_id")
        op.execute(f"ALTER TABLE {table} DROP COLUMN IF EXISTS batch_id")
    op.execute("DROP TABLE IF EXISTS metric_check_history CASCADE")
    op.execute("DROP TABLE IF EXISTS batch_logs CASCADE")
    op.execute("DROP TABLE IF EXISTS batches CASCADE")
