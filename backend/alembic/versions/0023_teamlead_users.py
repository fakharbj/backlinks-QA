"""TeamLead → member assignments (Phase 9 finalization).

Revision ID: 0023_teamlead_users
Revises: 0022_workforce
Create Date: 2026-07-03
"""

from __future__ import annotations

from alembic import op

import app.models  # noqa: F401,E402
from app.models.workforce import TeamLeadAssignment

revision = "0023_teamlead_users"
down_revision = "0022_workforce"
branch_labels = None
depends_on = None


def upgrade() -> None:
    TeamLeadAssignment.__table__.create(bind=op.get_bind(), checkfirst=True)


def downgrade() -> None:
    op.execute("DROP TABLE IF EXISTS teamlead_users CASCADE")
