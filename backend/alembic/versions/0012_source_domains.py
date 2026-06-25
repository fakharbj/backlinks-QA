"""Source main-domain aggregates (Phase 8, features 11/12/14).

Adds ``source_domains`` (per-workspace aggregate counters) + a
``backlink_records.source_domain_id`` FK. No backfill here — the aggregates are
populated by ``source_domain_service.recompute`` (run post-deploy + after each
import), so the heavy grouping lives in one reusable place.

Revision ID: 0012_source_domains
Revises: 0011_employee_codes
Create Date: 2026-06-26
"""

from __future__ import annotations

from alembic import op

# Register models on Base.metadata.
import app.models  # noqa: F401,E402
from app.models.source_domain import SourceDomain

revision = "0012_source_domains"
down_revision = "0011_employee_codes"
branch_labels = None
depends_on = None


def upgrade() -> None:
    bind = op.get_bind()
    SourceDomain.__table__.create(bind=bind, checkfirst=True)
    op.execute(
        "ALTER TABLE backlink_records ADD COLUMN IF NOT EXISTS source_domain_id uuid"
    )
    op.execute(
        "CREATE INDEX IF NOT EXISTS ix_backlink_records_source_domain_id "
        "ON backlink_records (source_domain_id)"
    )


def downgrade() -> None:
    op.execute("DROP INDEX IF EXISTS ix_backlink_records_source_domain_id")
    op.execute("ALTER TABLE backlink_records DROP COLUMN IF EXISTS source_domain_id")
    op.execute("DROP TABLE IF EXISTS source_domains CASCADE;")
