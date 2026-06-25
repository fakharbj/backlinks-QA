"""Project settings + main domains (Phase 8, feature 2).

Adds ``project_settings`` (1:1 with a project) and ``project_domains`` (1:N, one
primary), then backfills: a settings row per project (carrying the existing
``treat_sponsored_as_follow``) and a primary domain row from any existing
``projects.target_domain``. Additive + idempotent; nothing changes QA/link-matching
behaviour yet (the domains are stored + exposed only).

Revision ID: 0009_project_settings_domains
Revises: 0008_backlink_conflicts
Create Date: 2026-06-26
"""

from __future__ import annotations

from alembic import op

# Register models on Base.metadata.
import app.models  # noqa: F401,E402
from app.models.project_settings import ProjectDomain, ProjectSettings

revision = "0009_project_settings_domains"
down_revision = "0008_backlink_conflicts"
branch_labels = None
depends_on = None


def upgrade() -> None:
    bind = op.get_bind()
    ProjectSettings.__table__.create(bind=bind, checkfirst=True)
    ProjectDomain.__table__.create(bind=bind, checkfirst=True)
    # Safety net in case the table pre-existed (partial unique: one primary/project).
    op.execute(
        "CREATE UNIQUE INDEX IF NOT EXISTS uq_project_domains_one_primary "
        "ON project_domains (project_id) WHERE is_primary;"
    )

    # Backfill a settings row per project (carry the existing sponsored policy).
    op.execute(
        """
        INSERT INTO project_settings (
            id, workspace_id, project_id, scoring_profile, index_expected,
            treat_sponsored_as_follow, status_thresholds, extra, created_at, updated_at)
        SELECT gen_random_uuid(), workspace_id, id, 'inherit_global', true,
            treat_sponsored_as_follow, jsonb_build_object('fail_below', 30, 'warn_below', 80),
            '{}'::jsonb, now(), now()
        FROM projects
        ON CONFLICT (project_id) DO NOTHING;
        """
    )
    # Backfill the primary main domain from projects.target_domain when present.
    op.execute(
        """
        INSERT INTO project_domains (
            id, workspace_id, project_id, domain, is_primary, created_at, updated_at)
        SELECT gen_random_uuid(), workspace_id, id, lower(btrim(target_domain)), true,
            now(), now()
        FROM projects
        WHERE target_domain IS NOT NULL AND btrim(target_domain) <> ''
        ON CONFLICT (project_id, domain) DO NOTHING;
        """
    )


def downgrade() -> None:
    op.execute("DROP TABLE IF EXISTS project_domains CASCADE;")
    op.execute("DROP TABLE IF EXISTS project_settings CASCADE;")
