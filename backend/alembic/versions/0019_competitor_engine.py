"""Competitor backlink analysis tables (Phase 8).

Adds competitor_sheets, competitor_backlinks, competitor_source_domains. Additive +
idempotent (checkfirst).

Revision ID: 0019_competitor_engine
Revises: 0018_report_pivot_types
Create Date: 2026-06-26
"""

from __future__ import annotations

from alembic import op

import app.models  # noqa: F401,E402
from app.models.competitor import (
    CompetitorBacklink,
    CompetitorSheet,
    CompetitorSourceDomain,
)

revision = "0019_competitor_engine"
down_revision = "0018_report_pivot_types"
branch_labels = None
depends_on = None


def upgrade() -> None:
    bind = op.get_bind()
    CompetitorSheet.__table__.create(bind=bind, checkfirst=True)
    CompetitorBacklink.__table__.create(bind=bind, checkfirst=True)
    CompetitorSourceDomain.__table__.create(bind=bind, checkfirst=True)


def downgrade() -> None:
    op.execute("DROP TABLE IF EXISTS competitor_source_domains CASCADE")
    op.execute("DROP TABLE IF EXISTS competitor_backlinks CASCADE")
    op.execute("DROP TABLE IF EXISTS competitor_sheets CASCADE")
