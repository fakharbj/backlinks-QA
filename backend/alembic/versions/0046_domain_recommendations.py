"""Domain recommendations table (Phase 10 P4).

Task-based source-domain recommendations: what the engine (or an admin) suggested
to whom, and what they did with it (suggested → viewed → accepted | skipped).
Keyed by domain_key (no FK to source_domains — survives catalog recompute).

Revision ID: 0046_domain_recommendations
Revises: 0045_link_history_events
Create Date: 2026-07-11
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op

revision = "0046_domain_recommendations"
down_revision = "0045_link_history_events"
branch_labels = None
depends_on = None


def upgrade() -> None:
    bind = op.get_bind()
    exists = bind.execute(
        sa.text("SELECT 1 FROM information_schema.tables WHERE table_name='domain_recommendations'")
    ).first()
    if exists:
        return
    op.execute(
        """
        CREATE TABLE domain_recommendations (
            id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
            workspace_id UUID NOT NULL REFERENCES workspaces(id) ON DELETE CASCADE,
            project_id UUID NULL,
            domain_key VARCHAR(255) NOT NULL,
            assignment_id UUID NULL,
            recommended_to VARCHAR(200) NULL,
            link_type_name VARCHAR(80) NULL,
            source VARCHAR(10) NOT NULL DEFAULT 'auto',
            status VARCHAR(12) NOT NULL DEFAULT 'suggested',
            reason VARCHAR(300) NULL,
            priority VARCHAR(10) NULL,
            due_date DATE NULL,
            note VARCHAR(300) NULL,
            actor_user_id UUID NULL,
            created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
            updated_at TIMESTAMPTZ NOT NULL DEFAULT now()
        )
        """
    )
    # Nullable project/person → coalesce-based unique index (one row per scope).
    op.execute(
        """
        CREATE UNIQUE INDEX uq_domain_reco_scope ON domain_recommendations (
            workspace_id,
            coalesce(project_id, '00000000-0000-0000-0000-000000000000'::uuid),
            domain_key,
            coalesce(recommended_to, '')
        )
        """
    )
    op.execute(
        "CREATE INDEX ix_domain_reco_person ON domain_recommendations "
        "(workspace_id, recommended_to, status)"
    )
    op.execute(
        "CREATE INDEX ix_domain_reco_project ON domain_recommendations (workspace_id, project_id)"
    )


def downgrade() -> None:
    op.execute("DROP TABLE IF EXISTS domain_recommendations")
