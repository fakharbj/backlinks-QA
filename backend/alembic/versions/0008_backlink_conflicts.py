"""Backlink conflict (duplicate) groups (Phase 8, feature 9).

Adds ``backlink_conflicts`` + ``backlink_conflict_members`` and backfills groups
from existing data: any canonical source URL (``canonical_url_id`` from 0007)
referenced by >= 2 backlinks becomes a group, scoped same_project / cross_project /
cross_user. Additive + idempotent; read-only views consume it, so applying this
changes no crawl/import behaviour.

Revision ID: 0008_backlink_conflicts
Revises: 0007_canonical_urls
Create Date: 2026-06-26
"""

from __future__ import annotations

from alembic import op

# Register models on Base.metadata.
import app.models  # noqa: F401,E402
from app.models.conflict import BacklinkConflict, BacklinkConflictMember

revision = "0008_backlink_conflicts"
down_revision = "0007_canonical_urls"
branch_labels = None
depends_on = None


def upgrade() -> None:
    bind = op.get_bind()
    BacklinkConflict.__table__.create(bind=bind, checkfirst=True)
    BacklinkConflictMember.__table__.create(bind=bind, checkfirst=True)

    # Backfill groups: any canonical source URL shared by >= 2 backlinks.
    op.execute(
        """
        INSERT INTO backlink_conflicts (
            id, workspace_id, canonical_url_id, project_id, scope,
            resolution_status, member_count, detected_at, created_at, updated_at)
        SELECT gen_random_uuid(), workspace_id, canonical_url_id,
            CASE WHEN count(DISTINCT project_id) = 1 THEN (array_agg(DISTINCT project_id))[1] ELSE NULL END,
            CASE WHEN count(DISTINCT project_id) > 1 THEN 'cross_project'
                 WHEN count(DISTINCT nullif(assigned_user_label, '')) > 1 THEN 'cross_user'
                 ELSE 'same_project' END,
            'open', count(*), now(), now(), now()
        FROM backlink_records
        WHERE canonical_url_id IS NOT NULL
        GROUP BY workspace_id, canonical_url_id
        HAVING count(*) > 1
        ON CONFLICT (workspace_id, canonical_url_id) DO NOTHING;
        """
    )
    op.execute(
        """
        INSERT INTO backlink_conflict_members (id, conflict_id, backlink_id, created_at, updated_at)
        SELECT gen_random_uuid(), c.id, b.id, now(), now()
        FROM backlink_conflicts c
        JOIN backlink_records b
          ON b.workspace_id = c.workspace_id AND b.canonical_url_id = c.canonical_url_id
        ON CONFLICT (conflict_id, backlink_id) DO NOTHING;
        """
    )


def downgrade() -> None:
    op.execute("DROP TABLE IF EXISTS backlink_conflict_members CASCADE;")
    op.execute("DROP TABLE IF EXISTS backlink_conflicts CASCADE;")
