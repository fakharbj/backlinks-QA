"""Pending Project-Sheet-URL change on a sheet source: when the main sheet
points a project at a DIFFERENT spreadsheet, the new target is parked in these
columns (instead of silently repointing + resyncing) until an admin confirms it.

sheet_sources.pending_spreadsheet_id / pending_source_url / url_change_detected_at.
All nullable + additive → safe/instant.

Revision ID: 0059_sheet_pending_url_change
Revises: 0058_backlink_source_credentials
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op

revision = "0059_sheet_pending_url_change"
down_revision = "0058_backlink_source_credentials"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column("sheet_sources", sa.Column("pending_spreadsheet_id", sa.String(length=120), nullable=True))
    op.add_column("sheet_sources", sa.Column("pending_source_url", sa.String(length=1000), nullable=True))
    op.add_column("sheet_sources", sa.Column("url_change_detected_at", sa.DateTime(timezone=True), nullable=True))


def downgrade() -> None:
    op.drop_column("sheet_sources", "url_change_detected_at")
    op.drop_column("sheet_sources", "pending_source_url")
    op.drop_column("sheet_sources", "pending_spreadsheet_id")
