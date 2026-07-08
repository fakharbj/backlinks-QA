"""Canonical-label alias layer on user_employee_mappings.

The Google sheets' free-text "User" column has spelling variants (KEVIN / Keven /
KEVEN) and even different names for one person (Kashif == Kevin), which split one
person into many in the dashboards/performance. ``canonical_label`` turns a
mapping row into an ALIAS: when set, that ``sheet_user_label`` is a variant that
rolls up to ``canonical_label``. Every write of ``backlink_records.assigned_user_label``
(and the parallel workforce label columns) normalizes variants to the canonical
string, so grouping/filtering — which all key on the stored label — collapse the
person into one row and never re-split on a re-sync. NULL = the label is its own
canonical identity (unmerged). Additive/nullable: existing mappings are unchanged.

Revision ID: 0042_mapping_canonical_label
Revises: 0041_source_domain_discovery
Create Date: 2026-07-08
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op

revision = "0042_mapping_canonical_label"
down_revision = "0041_source_domain_discovery"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "user_employee_mappings",
        sa.Column("canonical_label", sa.String(length=200), nullable=True),
    )
    # Partial index the alias-map loader hits (only alias rows).
    op.execute(
        "CREATE INDEX IF NOT EXISTS ix_user_emp_map_canonical "
        "ON user_employee_mappings (workspace_id) WHERE canonical_label IS NOT NULL"
    )


def downgrade() -> None:
    op.execute("DROP INDEX IF EXISTS ix_user_emp_map_canonical")
    op.drop_column("user_employee_mappings", "canonical_label")
