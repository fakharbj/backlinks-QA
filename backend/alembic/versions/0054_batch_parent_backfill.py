"""Backfill ``meta.parent_batch_id`` on historical sheet_sync child batches.

New children get the pointer at creation (sheet_sync_service). Historical
children are matched to their bulk parent (kind=sheet_sync_all) by: the parent
tracks the project under a ``p:<sheet_source_id>`` meta key, and the child
started inside the parent's run window (small grace margins; bulk children are
queued with staggered countdowns). If a child could match several parents the
most recent one wins. Standalone manual syncs (no matching parent window) are
left untouched and keep appearing as their own top-level row.

Revision ID: 0054_batch_parent_backfill
Revises: 0053_scoring_v2_zero_deductions
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op

revision = "0054_batch_parent_backfill"
down_revision = "0053_scoring_v2_zero_deductions"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.get_bind().execute(
        sa.text(
            """
            WITH candidates AS (
                SELECT c.id AS child_id,
                       p.id AS parent_id,
                       row_number() OVER (
                           PARTITION BY c.id ORDER BY p.started_at DESC
                       ) AS rn
                FROM batches c
                JOIN batches p
                  ON p.kind = 'sheet_sync_all'
                 AND p.workspace_id = c.workspace_id
                 AND p.meta ? ('p:' || (c.meta->>'sheet_source_id'))
                 AND c.started_at >= p.started_at - interval '2 minutes'
                 AND c.started_at <= coalesce(p.finished_at, p.started_at + interval '6 hours')
                                     + interval '2 minutes'
                WHERE c.kind = 'sheet_sync'
                  AND c.meta->>'sheet_source_id' IS NOT NULL
                  AND c.meta->>'parent_batch_id' IS NULL
            )
            UPDATE batches b
            SET meta = b.meta || jsonb_build_object('parent_batch_id', cand.parent_id::text)
            FROM candidates cand
            WHERE b.id = cand.child_id AND cand.rn = 1
            """
        )
    )


def downgrade() -> None:
    op.get_bind().execute(
        sa.text("UPDATE batches SET meta = meta - 'parent_batch_id' WHERE kind = 'sheet_sync'")
    )
