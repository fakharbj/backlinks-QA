"""Date-type lifecycle columns on ``backlink_records``.

Adds four TIMESTAMPTZ lifecycle timestamps so the grid/filters/exports can slice
links by *when things happened*, alongside the existing DATE inputs
(``placement_date``, ``sheet_created_date``):

* ``discovered_at``    — when the link first entered our DB (import/sync insert).
* ``first_qa_at``      — the first crawl/QA verdict timestamp.
* ``qa_completed_at``  — when QA reached a terminal (non-PENDING) verdict.
* ``assigned_at``      — the latest assignment change (from assignment_history).

All four are nullable and backfilled in a single set-based pass (data is modest).
Also adds sargable indexes for the two new hot ranges plus the existing DATE
inputs (``placement_date``, ``sheet_created_date``) now that they are filterable.

Revision ID: 0031_date_types
Revises: 0030_sheet_mapping_flex
Create Date: 2026-07-07
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op

revision = "0031_date_types"
down_revision = "0030_sheet_mapping_flex"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "backlink_records",
        sa.Column("discovered_at", sa.DateTime(timezone=True), nullable=True),
    )
    op.add_column(
        "backlink_records",
        sa.Column("first_qa_at", sa.DateTime(timezone=True), nullable=True),
    )
    op.add_column(
        "backlink_records",
        sa.Column("qa_completed_at", sa.DateTime(timezone=True), nullable=True),
    )
    op.add_column(
        "backlink_records",
        sa.Column("assigned_at", sa.DateTime(timezone=True), nullable=True),
    )

    # ── Backfill (single set-based pass; data volume is modest) ────────────────
    # Discovery = when the row reached our DB.
    op.execute(
        "UPDATE backlink_records SET discovered_at = created_at "
        "WHERE discovered_at IS NULL"
    )
    # First QA = earliest crawl result for the link.
    op.execute(
        "UPDATE backlink_records b SET first_qa_at = s.mn "
        "FROM (SELECT backlink_id, min(crawled_at) AS mn FROM crawl_results "
        "GROUP BY backlink_id) s "
        "WHERE b.id = s.backlink_id AND b.first_qa_at IS NULL"
    )
    # QA completion = first_qa_at once the verdict is terminal (not PENDING).
    op.execute(
        "UPDATE backlink_records b SET qa_completed_at = b.first_qa_at "
        "WHERE b.status <> 'PENDING' "
        "AND b.qa_completed_at IS NULL AND b.first_qa_at IS NOT NULL"
    )
    # Assignment = latest recorded assignment change for the link.
    op.execute(
        "UPDATE backlink_records b SET assigned_at = a.mx "
        "FROM (SELECT backlink_id, max(changed_at) AS mx FROM assignment_history "
        "GROUP BY backlink_id) a "
        "WHERE b.id = a.backlink_id AND b.assigned_at IS NULL"
    )

    # ── Indexes ───────────────────────────────────────────────────────────────
    op.create_index(
        "ix_backlink_records_discovered", "backlink_records", ["discovered_at"]
    )
    op.create_index(
        "ix_backlink_records_qa_completed", "backlink_records", ["qa_completed_at"]
    )
    op.create_index(
        "ix_backlink_records_placement", "backlink_records", ["placement_date"]
    )
    op.create_index(
        "ix_backlink_records_sheet_created", "backlink_records", ["sheet_created_date"]
    )


def downgrade() -> None:
    op.drop_index("ix_backlink_records_sheet_created", table_name="backlink_records")
    op.drop_index("ix_backlink_records_placement", table_name="backlink_records")
    op.drop_index("ix_backlink_records_qa_completed", table_name="backlink_records")
    op.drop_index("ix_backlink_records_discovered", table_name="backlink_records")
    op.drop_column("backlink_records", "assigned_at")
    op.drop_column("backlink_records", "qa_completed_at")
    op.drop_column("backlink_records", "first_qa_at")
    op.drop_column("backlink_records", "discovered_at")
