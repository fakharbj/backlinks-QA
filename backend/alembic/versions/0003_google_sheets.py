"""Google Sheets ingest: sheet_sources table + sheet-sourced backlink columns.

Adds the SheetSource table (one per connected project sheet) and the input fields
the sheet owns on backlink_records (assigned user/employee, link type, sheet
refs), plus imports.sheet_source_id.

Revision ID: 0003_google_sheets
Revises: 0002_drop_dashboard_matviews
Create Date: 2026-06-24
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects.postgresql import UUID as PGUUID

# Register all tables (incl. SheetSource) on Base.metadata.
import app.models  # noqa: F401,E402
from app.models.sheets import SheetSource

revision = "0003_google_sheets"
down_revision = "0002_drop_dashboard_matviews"
branch_labels = None
depends_on = None


def upgrade() -> None:
    bind = op.get_bind()

    # 1) sheet_sources (from the ORM definition, with its indexes/constraints).
    SheetSource.__table__.create(bind=bind, checkfirst=True)

    # 2) imports.sheet_source_id
    op.add_column("imports", sa.Column("sheet_source_id", PGUUID(as_uuid=True), nullable=True))

    # 3) backlink_records: sheet-sourced input fields.
    op.add_column("backlink_records", sa.Column("assigned_user_label", sa.String(200), nullable=True))
    op.add_column("backlink_records", sa.Column("employee_code", sa.String(60), nullable=True))
    op.add_column("backlink_records", sa.Column("link_type", sa.String(60), nullable=True))
    op.add_column("backlink_records", sa.Column("source_sheet_id", PGUUID(as_uuid=True), nullable=True))
    op.add_column("backlink_records", sa.Column("sheet_row_ref", sa.String(40), nullable=True))
    op.add_column("backlink_records", sa.Column("sheet_created_date", sa.Date(), nullable=True))

    op.create_foreign_key(
        "fk_backlink_records_source_sheet", "backlink_records", "sheet_sources",
        ["source_sheet_id"], ["id"], ondelete="SET NULL",
    )
    op.create_index("ix_backlink_records_source_sheet", "backlink_records", ["source_sheet_id"])
    op.create_index("ix_backlink_records_assigned_label", "backlink_records", ["assigned_user_label"])
    op.create_index("ix_backlink_records_link_type", "backlink_records", ["link_type"])


def downgrade() -> None:
    op.drop_index("ix_backlink_records_link_type", table_name="backlink_records")
    op.drop_index("ix_backlink_records_assigned_label", table_name="backlink_records")
    op.drop_index("ix_backlink_records_source_sheet", table_name="backlink_records")
    op.drop_constraint("fk_backlink_records_source_sheet", "backlink_records", type_="foreignkey")
    for col in (
        "sheet_created_date", "sheet_row_ref", "source_sheet_id",
        "link_type", "employee_code", "assigned_user_label",
    ):
        op.drop_column("backlink_records", col)
    op.drop_column("imports", "sheet_source_id")
    op.execute("DROP TABLE IF EXISTS sheet_sources CASCADE;")
