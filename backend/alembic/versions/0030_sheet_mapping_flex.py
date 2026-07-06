"""Flexible per-tab sheet mapping.

Adds per-tab mapping overrides to ``google_sheet_project_tabs`` so each tab can:
* ``column_mapping`` — override the header→canonical-field map (null = inherit the
  source-level default, then fall back to auto-map).
* ``field_constants`` — set a literal value for a canonical field on every row of
  the tab (e.g. force ``link_type`` = the tab name).
* ``header_row`` — the 1-based row the headers actually live on (null = row 1).
* ``headers_snapshot`` — the last-seen header list, powering the mapping UI + drift
  detection without a live read.

Revision ID: 0030_sheet_mapping_flex
Revises: 0029_batch_review
Create Date: 2026-07-06
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects.postgresql import JSONB

revision = "0030_sheet_mapping_flex"
down_revision = "0029_batch_review"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "google_sheet_project_tabs", sa.Column("column_mapping", JSONB(), nullable=True)
    )
    op.add_column(
        "google_sheet_project_tabs", sa.Column("field_constants", JSONB(), nullable=True)
    )
    op.add_column(
        "google_sheet_project_tabs", sa.Column("header_row", sa.Integer(), nullable=True)
    )
    op.add_column(
        "google_sheet_project_tabs", sa.Column("headers_snapshot", JSONB(), nullable=True)
    )


def downgrade() -> None:
    op.drop_column("google_sheet_project_tabs", "headers_snapshot")
    op.drop_column("google_sheet_project_tabs", "header_row")
    op.drop_column("google_sheet_project_tabs", "field_constants")
    op.drop_column("google_sheet_project_tabs", "column_mapping")
