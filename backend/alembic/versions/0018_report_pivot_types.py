"""Add pivot/summary report types (Phase 8).

Extends the native ``report_type_enum`` with SOURCE_DOMAIN_SUMMARY,
LINK_TYPE_SUMMARY and USER_PERFORMANCE. Postgres 12+ allows ADD VALUE inside a
transaction (we don't use the new values in this migration). Idempotent via
IF NOT EXISTS.

Revision ID: 0018_report_pivot_types
Revises: 0017_scoring_engine_wire
Create Date: 2026-06-26
"""

from __future__ import annotations

from alembic import op

revision = "0018_report_pivot_types"
down_revision = "0017_scoring_engine_wire"
branch_labels = None
depends_on = None

_VALUES = ("source_domain_summary", "link_type_summary", "user_performance")


def upgrade() -> None:
    for v in _VALUES:
        op.execute(f"ALTER TYPE report_type_enum ADD VALUE IF NOT EXISTS '{v}'")


def downgrade() -> None:
    # Postgres cannot drop a single enum value; leaving the values is harmless.
    pass
