"""Employee codes + sheet-user mappings (Phase 8, feature 3).

Adds ``employee_codes`` (workspace catalog) + ``user_employee_mappings`` (sheet
label → app user / code), then backfills both from existing backlink data: distinct
employee codes, and distinct sheet "User" labels (auto-linking to the app user that
import already resolved via ``assigned_user_id``). Additive + idempotent.

Revision ID: 0011_employee_codes
Revises: 0010_store_duplicate_backlinks
Create Date: 2026-06-26
"""

from __future__ import annotations

from alembic import op

# Register models on Base.metadata.
import app.models  # noqa: F401,E402
from app.models.employee import EmployeeCode, UserEmployeeMapping

revision = "0011_employee_codes"
down_revision = "0010_store_duplicate_backlinks"
branch_labels = None
depends_on = None


def upgrade() -> None:
    bind = op.get_bind()
    EmployeeCode.__table__.create(bind=bind, checkfirst=True)
    UserEmployeeMapping.__table__.create(bind=bind, checkfirst=True)

    # Backfill the code catalog from distinct sheet employee codes.
    op.execute(
        """
        INSERT INTO employee_codes (id, workspace_id, code, is_active, created_at, updated_at)
        SELECT gen_random_uuid(), workspace_id, code, true, now(), now()
        FROM (
            SELECT DISTINCT workspace_id, btrim(employee_code) AS code
            FROM backlink_records
            WHERE employee_code IS NOT NULL AND btrim(employee_code) <> ''
        ) t
        ON CONFLICT (workspace_id, code) DO NOTHING;
        """
    )
    # Backfill label→user mappings (auto-link to the app user import already resolved).
    op.execute(
        """
        INSERT INTO user_employee_mappings (
            id, workspace_id, sheet_user_label, user_id, is_current, created_at, updated_at)
        SELECT gen_random_uuid(), workspace_id, label,
            (array_agg(assigned_user_id) FILTER (WHERE assigned_user_id IS NOT NULL))[1],
            true, now(), now()
        FROM (
            SELECT workspace_id, btrim(assigned_user_label) AS label, assigned_user_id
            FROM backlink_records
            WHERE assigned_user_label IS NOT NULL AND btrim(assigned_user_label) <> ''
        ) t
        GROUP BY workspace_id, label
        ON CONFLICT (workspace_id, sheet_user_label) DO NOTHING;
        """
    )


def downgrade() -> None:
    op.execute("DROP TABLE IF EXISTS user_employee_mappings CASCADE;")
    op.execute("DROP TABLE IF EXISTS employee_codes CASCADE;")
