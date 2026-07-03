"""Competitor opportunity lifecycle (Phase 9 P1).

Adds ``competitor_domain_decisions`` — manual opportunity decisions (dismissed /
re-opened) that survive the DELETE+INSERT domain recompute — and a
``link_type_label`` on competitor backlinks (e.g. "Guest Post") so opportunity
lists can tag and exclude by type. Additive + idempotent.

Revision ID: 0021_competitor_lifecycle
Revises: 0020_batches_metric_history
Create Date: 2026-07-03
"""

from __future__ import annotations

from alembic import op

import app.models  # noqa: F401,E402
from app.models.competitor import CompetitorDomainDecision

revision = "0021_competitor_lifecycle"
down_revision = "0020_batches_metric_history"
branch_labels = None
depends_on = None


def upgrade() -> None:
    bind = op.get_bind()
    CompetitorDomainDecision.__table__.create(bind=bind, checkfirst=True)
    op.execute(
        "ALTER TABLE competitor_backlinks ADD COLUMN IF NOT EXISTS link_type_label varchar(120)"
    )


def downgrade() -> None:
    op.execute("ALTER TABLE competitor_backlinks DROP COLUMN IF EXISTS link_type_label")
    op.execute("DROP TABLE IF EXISTS competitor_domain_decisions CASCADE")
