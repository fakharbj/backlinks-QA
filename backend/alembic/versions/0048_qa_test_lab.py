"""Temp QA lab — candidate backlink tests, fully isolated (Phase 11).

A completely separate space for QA-testing candidates' backlinks: each test
holds a candidate's details + their submitted links, auto-QA'd by the SAME
engine but stored ONLY here. Nothing touches backlink_records, projects,
dashboards, analytics, source_domains or any production data.

Revision ID: 0048_qa_test_lab
Revises: 0047_qa_attempts_wait_reason
Create Date: 2026-07-17
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op

revision = "0048_qa_test_lab"
down_revision = "0047_qa_attempts_wait_reason"
branch_labels = None
depends_on = None


def upgrade() -> None:
    bind = op.get_bind()
    exists = bind.execute(
        sa.text("SELECT 1 FROM information_schema.tables WHERE table_name='qa_test_batches'")
    ).first()
    if exists:
        return
    op.execute(
        """
        CREATE TABLE qa_test_batches (
            id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
            workspace_id UUID NOT NULL REFERENCES workspaces(id) ON DELETE CASCADE,
            candidate_name VARCHAR(200) NOT NULL,
            candidate_email VARCHAR(255) NULL,
            role_applied VARCHAR(120) NULL,
            notes VARCHAR(1000) NULL,
            status VARCHAR(12) NOT NULL DEFAULT 'draft',
            created_by UUID NULL,
            created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
            updated_at TIMESTAMPTZ NOT NULL DEFAULT now()
        )
        """
    )
    op.execute(
        "CREATE INDEX ix_qa_test_batches_ws ON qa_test_batches (workspace_id, created_at DESC)"
    )
    op.execute(
        """
        CREATE TABLE qa_test_links (
            id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
            batch_id UUID NOT NULL REFERENCES qa_test_batches(id) ON DELETE CASCADE,
            workspace_id UUID NOT NULL REFERENCES workspaces(id) ON DELETE CASCADE,
            source_url TEXT NOT NULL,
            target_url TEXT NULL,
            anchor_text VARCHAR(500) NULL,
            link_type VARCHAR(80) NULL,
            expected_rel VARCHAR(20) NULL,
            state VARCHAR(12) NOT NULL DEFAULT 'pending',
            status VARCHAR(24) NULL,
            score INTEGER NULL,
            link_found BOOLEAN NULL,
            http_status INTEGER NULL,
            current_rel VARCHAR(20) NULL,
            current_anchor VARCHAR(500) NULL,
            indexability VARCHAR(20) NULL,
            matched_href TEXT NULL,
            top_issue VARCHAR(80) NULL,
            facts JSONB NOT NULL DEFAULT '{}'::jsonb,
            error VARCHAR(500) NULL,
            checked_at TIMESTAMPTZ NULL,
            created_at TIMESTAMPTZ NOT NULL DEFAULT now()
        )
        """
    )
    op.execute(
        "CREATE INDEX ix_qa_test_links_batch ON qa_test_links (batch_id, created_at)"
    )


def downgrade() -> None:
    op.execute("DROP TABLE IF EXISTS qa_test_links")
    op.execute("DROP TABLE IF EXISTS qa_test_batches")
