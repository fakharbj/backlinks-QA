"""QA attempt audit trail + API-failure wait states (Enterprise refinement §1-3).

A recoverable EXTERNAL failure (proxy limit/outage, timeout, rate limit) must not
auto-retry forever: the link keeps its Pending/Unknown verdict but gets a
``qa_wait_reason`` (waiting_api | api_failed) and ``next_check_at`` is cleared —
QA runs again only when a human retries (or quota returns and they choose to).
``qa_attempts`` records EVERY execution try — success, failure, or blocked —
with the APIs used, duration, and error, becoming the QA audit trail.

Revision ID: 0047_qa_attempts_wait_reason
Revises: 0046_domain_recommendations
Create Date: 2026-07-12
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op

revision = "0047_qa_attempts_wait_reason"
down_revision = "0046_domain_recommendations"
branch_labels = None
depends_on = None


def upgrade() -> None:
    bind = op.get_bind()
    col = bind.execute(
        sa.text(
            "SELECT 1 FROM information_schema.columns "
            "WHERE table_name='backlink_records' AND column_name='qa_wait_reason'"
        )
    ).first()
    if not col:
        op.execute(
            "ALTER TABLE backlink_records ADD COLUMN qa_wait_reason VARCHAR(20) NULL"
        )
        op.execute(
            "CREATE INDEX ix_backlinks_qa_wait ON backlink_records (workspace_id, qa_wait_reason) "
            "WHERE qa_wait_reason IS NOT NULL"
        )
    tbl = bind.execute(
        sa.text("SELECT 1 FROM information_schema.tables WHERE table_name='qa_attempts'")
    ).first()
    if not tbl:
        op.execute(
            """
            CREATE TABLE qa_attempts (
                id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
                workspace_id UUID NOT NULL REFERENCES workspaces(id) ON DELETE CASCADE,
                backlink_id UUID NOT NULL,
                attempt_number INT NOT NULL DEFAULT 1,
                trigger_source VARCHAR(12) NOT NULL DEFAULT 'auto',
                triggered_by UUID NULL,
                queue VARCHAR(30) NULL,
                apis_used JSONB NOT NULL DEFAULT '[]'::jsonb,
                request_count INT NOT NULL DEFAULT 1,
                duration_ms INT NULL,
                status VARCHAR(12) NOT NULL,
                verdict VARCHAR(30) NULL,
                failure_kind VARCHAR(30) NULL,
                failure_api VARCHAR(30) NULL,
                error VARCHAR(500) NULL,
                created_at TIMESTAMPTZ NOT NULL DEFAULT now()
            )
            """
        )
        op.execute(
            "CREATE INDEX ix_qa_attempts_backlink ON qa_attempts (backlink_id, created_at DESC)"
        )
        op.execute(
            "CREATE INDEX ix_qa_attempts_ws ON qa_attempts (workspace_id, created_at DESC)"
        )


def downgrade() -> None:
    op.execute("DROP TABLE IF EXISTS qa_attempts")
    op.execute("DROP INDEX IF EXISTS ix_backlinks_qa_wait")
    op.execute("ALTER TABLE backlink_records DROP COLUMN IF EXISTS qa_wait_reason")
