"""Batch review layer (staged imports + domain imports).

* ``batches.seq`` — human-friendly sequential number (#B-142) from a global
  sequence, backfilled over existing rows in start order.
* ``batch_items`` — the staging rows of a review batch (one per pasted link /
  imported domain). Items live and die with their batch and NEVER touch the
  production tables until explicitly approved.
* ``source_domains.origin`` — 'derived' rows are rebuilt from backlinks by
  recompute (and orphan-deleted); 'imported' rows were approved from a domain
  import batch and must survive recompute even with zero backlinks.

Revision ID: 0029_batch_review
Revises: 0028_template_id_default
Create Date: 2026-07-06
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects.postgresql import JSONB, UUID

revision = "0029_batch_review"
down_revision = "0028_template_id_default"
branch_labels = None
depends_on = None


def upgrade() -> None:
    # ── batches.seq ──────────────────────────────────────────────────────────
    # Add WITHOUT a default first: a volatile default (nextval) would number
    # existing rows in physical order — backfill chronologically instead, then
    # attach the sequence default for new rows.
    op.execute("CREATE SEQUENCE IF NOT EXISTS batches_seq_seq")
    op.add_column("batches", sa.Column("seq", sa.BigInteger(), nullable=True))
    op.execute(
        """
        UPDATE batches SET seq = sub.rn
        FROM (
            SELECT id, row_number() OVER (ORDER BY started_at ASC, id ASC) AS rn
            FROM batches
        ) sub
        WHERE batches.id = sub.id
        """
    )
    op.execute(
        "SELECT setval('batches_seq_seq', coalesce((SELECT max(seq) FROM batches), 0) + 1, false)"
    )
    op.execute("ALTER TABLE batches ALTER COLUMN seq SET DEFAULT nextval('batches_seq_seq')")
    op.execute("ALTER SEQUENCE batches_seq_seq OWNED BY batches.seq")
    op.alter_column("batches", "seq", nullable=False)
    op.create_index("ix_batches_seq", "batches", ["seq"], unique=False)

    # ── batch_items ──────────────────────────────────────────────────────────
    op.create_table(
        "batch_items",
        sa.Column("id", UUID(as_uuid=True), primary_key=True, server_default=sa.text("gen_random_uuid()")),
        sa.Column("workspace_id", UUID(as_uuid=True), nullable=False),
        sa.Column(
            "batch_id",
            UUID(as_uuid=True),
            sa.ForeignKey("batches.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("project_id", UUID(as_uuid=True), nullable=True),
        sa.Column("kind", sa.String(10), nullable=False),  # link | domain
        sa.Column("label", sa.Text(), nullable=False),  # the URL / domain (display + search)
        sa.Column("key_hash", sa.String(64), nullable=False),  # sha256 identity within the batch
        sa.Column("presence", sa.String(12), nullable=False, server_default="new"),
        sa.Column("state", sa.String(12), nullable=False, server_default="pending"),
        sa.Column("payload", JSONB(), nullable=False, server_default=sa.text("'{}'::jsonb")),
        sa.Column("error", sa.Text(), nullable=True),
        sa.Column("checked_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("approved_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.UniqueConstraint("batch_id", "key_hash", name="uq_batch_items_batch_key"),
    )
    op.create_index("ix_batch_items_ws_batch_state", "batch_items", ["workspace_id", "batch_id", "state"])
    op.create_index("ix_batch_items_batch_created", "batch_items", ["batch_id", "created_at"])

    # ── source_domains.origin ────────────────────────────────────────────────
    op.add_column(
        "source_domains",
        sa.Column("origin", sa.String(12), nullable=False, server_default="derived"),
    )


def downgrade() -> None:
    op.drop_column("source_domains", "origin")
    op.drop_index("ix_batch_items_batch_created", table_name="batch_items")
    op.drop_index("ix_batch_items_ws_batch_state", table_name="batch_items")
    op.drop_table("batch_items")
    op.drop_index("ix_batches_seq", table_name="batches")
    op.drop_column("batches", "seq")
    op.execute("DROP SEQUENCE IF EXISTS batches_seq_seq")
