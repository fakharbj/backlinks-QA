"""Final production-hardening columns (all additive, NULL-safe on old rows).

* ``imports.new_rows`` / ``imports.updated_rows`` — honest import accounting:
  imported = new + refreshed. Old imports stay NULL (unknown split).
* ``task_assignments.priority`` — High/Medium/Low per assignment (owner-sheet
  parity); ``rate_source`` + ``lph_used`` — snapshot of WHICH productivity rate
  produced ``expected_links`` (global | override | manual) so history explains
  itself even after rates change.
* ``competitor_sheets.competitor_url`` — a competitor upload is now identified
  by the competitor's site URL (required in the API going forward); the display
  name stays optional and falls back to the domain.

Revision ID: 0026_finalization_columns
Revises: 0025_scale_indexes
Create Date: 2026-07-04
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op

revision = "0026_finalization_columns"
down_revision = "0025_scale_indexes"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column("imports", sa.Column("new_rows", sa.Integer(), nullable=True))
    op.add_column("imports", sa.Column("updated_rows", sa.Integer(), nullable=True))

    op.add_column("task_assignments", sa.Column("priority", sa.String(length=10), nullable=True))
    op.add_column("task_assignments", sa.Column("rate_source", sa.String(length=16), nullable=True))
    op.add_column("task_assignments", sa.Column("lph_used", sa.Numeric(6, 1), nullable=True))

    op.add_column(
        "competitor_sheets", sa.Column("competitor_url", sa.String(length=500), nullable=True)
    )


def downgrade() -> None:
    op.drop_column("competitor_sheets", "competitor_url")
    op.drop_column("task_assignments", "lph_used")
    op.drop_column("task_assignments", "rate_source")
    op.drop_column("task_assignments", "priority")
    op.drop_column("imports", "updated_rows")
    op.drop_column("imports", "new_rows")
