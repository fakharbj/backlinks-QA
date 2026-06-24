"""Link identity + duplicate detection + assignment history.

Adds link_identity (hash-keyed identity = source + target domain) and
assignment_history, plus duplicate columns on backlink_records, then backfills
identities + duplicate_status from existing data so the feature is live right
after upgrade. Column/index DDL uses IF NOT EXISTS for idempotency.

Revision ID: 0004_link_identity_duplicates
Revises: 0003_google_sheets
Create Date: 2026-06-24
"""

from __future__ import annotations

from alembic import op

# Register models on Base.metadata.
import app.models  # noqa: F401,E402
from app.models.link_identity import AssignmentHistory, LinkIdentity

revision = "0004_link_identity_duplicates"
down_revision = "0003_google_sheets"
branch_labels = None
depends_on = None


def upgrade() -> None:
    bind = op.get_bind()
    op.execute("CREATE EXTENSION IF NOT EXISTS pgcrypto;")  # for digest()

    LinkIdentity.__table__.create(bind=bind, checkfirst=True)
    AssignmentHistory.__table__.create(bind=bind, checkfirst=True)

    op.execute(
        "ALTER TABLE backlink_records "
        "ADD COLUMN IF NOT EXISTS link_identity_id uuid, "
        "ADD COLUMN IF NOT EXISTS is_duplicate boolean NOT NULL DEFAULT false, "
        "ADD COLUMN IF NOT EXISTS duplicate_status varchar(40)"
    )
    op.execute(
        "CREATE INDEX IF NOT EXISTS ix_backlink_records_identity "
        "ON backlink_records (link_identity_id)"
    )
    op.execute(
        "CREATE INDEX IF NOT EXISTS ix_backlink_records_duplicate "
        "ON backlink_records (workspace_id, duplicate_status)"
    )

    # ── Backfill from existing rows ──────────────────────────────────────────
    op.execute(
        """
        INSERT INTO link_identity (
            id, workspace_id, identity_key, source_url_normalized, target_domain,
            occurrence_count, project_count, user_count, target_url_count,
            first_seen_at, last_seen_at, created_at, updated_at)
        SELECT gen_random_uuid(), workspace_id,
            encode(digest(workspace_id::text || '|' || source_url_normalized || '|'
                   || coalesce(target_domain, ''), 'sha256'), 'hex'),
            source_url_normalized, coalesce(target_domain, ''),
            count(*), count(distinct project_id),
            count(distinct nullif(assigned_user_label, '')),
            count(distinct target_url_normalized),
            min(created_at), max(created_at), now(), now()
        FROM backlink_records
        GROUP BY workspace_id, source_url_normalized, coalesce(target_domain, '')
        ON CONFLICT (identity_key) DO NOTHING;
        """
    )
    op.execute(
        """
        UPDATE backlink_records b SET link_identity_id = li.id
        FROM link_identity li
        WHERE li.identity_key = encode(digest(
            b.workspace_id::text || '|' || b.source_url_normalized || '|'
            || coalesce(b.target_domain, ''), 'sha256'), 'hex');
        """
    )
    op.execute(
        """
        UPDATE backlink_records b SET
            is_duplicate = (li.occurrence_count > 1),
            duplicate_status = CASE
                WHEN li.occurrence_count <= 1 THEN 'unique'
                WHEN li.project_count > 1 THEN 'dup_cross_project'
                WHEN li.user_count > 1 THEN 'dup_cross_user'
                ELSE 'dup_same_project' END
        FROM link_identity li WHERE b.link_identity_id = li.id;
        """
    )


def downgrade() -> None:
    op.execute("DROP INDEX IF EXISTS ix_backlink_records_duplicate")
    op.execute("DROP INDEX IF EXISTS ix_backlink_records_identity")
    op.execute(
        "ALTER TABLE backlink_records "
        "DROP COLUMN IF EXISTS duplicate_status, "
        "DROP COLUMN IF EXISTS is_duplicate, "
        "DROP COLUMN IF EXISTS link_identity_id"
    )
    op.execute("DROP TABLE IF EXISTS assignment_history CASCADE;")
    op.execute("DROP TABLE IF EXISTS link_identity CASCADE;")
