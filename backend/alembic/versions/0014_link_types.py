"""Link-type catalog (Phase 8 — prerequisite for dynamic scoring).

Adds ``link_types`` (workspace catalog) + ``backlink_records.link_type_id`` FK, then
seeds the catalog from existing free-text ``backlink_records.link_type`` and backfills
``link_type_id``. Additive + idempotent.

Revision ID: 0014_link_types
Revises: 0013_domain_metrics
Create Date: 2026-06-26
"""

from __future__ import annotations

from alembic import op

# Register models on Base.metadata.
import app.models  # noqa: F401,E402
from app.models.link_type import LinkType

revision = "0014_link_types"
down_revision = "0013_domain_metrics"
branch_labels = None
depends_on = None


def upgrade() -> None:
    bind = op.get_bind()
    LinkType.__table__.create(bind=bind, checkfirst=True)
    op.execute("ALTER TABLE backlink_records ADD COLUMN IF NOT EXISTS link_type_id uuid")
    op.execute(
        "CREATE INDEX IF NOT EXISTS ix_backlink_records_link_type_id "
        "ON backlink_records (link_type_id)"
    )

    # Seed the catalog from distinct free-text link types.
    op.execute(
        """
        INSERT INTO link_types (id, workspace_id, name, slug, is_active, created_at, updated_at)
        SELECT gen_random_uuid(), workspace_id, name,
            trim(both '-' from lower(regexp_replace(name, '[^a-zA-Z0-9]+', '-', 'g'))),
            true, now(), now()
        FROM (
            SELECT DISTINCT workspace_id, btrim(link_type) AS name
            FROM backlink_records
            WHERE link_type IS NOT NULL AND btrim(link_type) <> ''
        ) t
        WHERE trim(both '-' from lower(regexp_replace(name, '[^a-zA-Z0-9]+', '-', 'g'))) <> ''
        ON CONFLICT (workspace_id, slug) DO NOTHING;
        """
    )
    # Backfill link_type_id by name (case-insensitive).
    op.execute(
        """
        UPDATE backlink_records b SET link_type_id = lt.id
        FROM link_types lt
        WHERE lt.workspace_id = b.workspace_id
          AND lower(lt.name) = lower(btrim(b.link_type))
          AND b.link_type IS NOT NULL AND btrim(b.link_type) <> '';
        """
    )


def downgrade() -> None:
    op.execute("DROP INDEX IF EXISTS ix_backlink_records_link_type_id")
    op.execute("ALTER TABLE backlink_records DROP COLUMN IF EXISTS link_type_id")
    op.execute("DROP TABLE IF EXISTS link_types CASCADE;")
