"""Domain enrichment (Phase 10 P2).

Three additive surfaces:
* ``source_domains`` — robots-txt rollup counters + a derived ``robots_band``
  (recompute-owned, like the index buckets), a write-once FIRST-metrics snapshot
  (``*_first`` + when/where it came from) so "what did this domain look like when
  we found it" survives every refresh, and manual ``market``/``country`` labels.
* ``metric_check_history`` — a ``values`` JSONB payload ({"old": {...}, "new":
  {...}}) so every check records what actually changed, plus a workspace/time
  index for the audit views.
* ``competitor_domain_decisions`` — ``assigned_to`` for the opportunity workflow
  and a wider ``status`` (the new vocabulary includes 22-char
  ``needs_link_type_review``; the existing ``reason`` column doubles as the note).

Everything is additive + idempotent (information_schema/pg_indexes guards, like
0043) so a re-run on a partially-migrated box is a no-op.

Revision ID: 0044_domain_enrichment
Revises: 0043_link_type_merge
Create Date: 2026-07-11
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.dialects.postgresql import UUID as PGUUID

revision = "0044_domain_enrichment"
down_revision = "0043_link_type_merge"
branch_labels = None
depends_on = None


def _has_column(bind, table: str, column: str) -> bool:
    return (
        bind.execute(
            sa.text(
                "SELECT 1 FROM information_schema.columns "
                "WHERE table_name = :t AND column_name = :c"
            ),
            {"t": table, "c": column},
        ).first()
        is not None
    )


def _has_index(bind, table: str, index: str) -> bool:
    return (
        bind.execute(
            sa.text("SELECT 1 FROM pg_indexes WHERE tablename = :t AND indexname = :i"),
            {"t": table, "i": index},
        ).first()
        is not None
    )


# (table, column object) — each add is guarded individually so a partial earlier
# run never blocks the rest.
def _new_columns() -> list[tuple[str, sa.Column]]:
    return [
        # Robots rollup — recompute-owned counters over backlink_records.robots_status.
        ("source_domains", sa.Column("robots_allowed_count", sa.Integer(), nullable=False, server_default="0")),
        ("source_domains", sa.Column("robots_blocked_count", sa.Integer(), nullable=False, server_default="0")),
        ("source_domains", sa.Column("robots_unknown_count", sa.Integer(), nullable=False, server_default="0")),
        ("source_domains", sa.Column("robots_band", sa.String(20), nullable=True)),
        # First-metrics snapshot — write-once originals (guarded on first_metrics_at IS NULL).
        ("source_domains", sa.Column("da_first", sa.Integer(), nullable=True)),
        ("source_domains", sa.Column("pa_first", sa.Integer(), nullable=True)),
        ("source_domains", sa.Column("spam_first", sa.Integer(), nullable=True)),
        ("source_domains", sa.Column("as_first", sa.Integer(), nullable=True)),
        ("source_domains", sa.Column("traffic_first", sa.BigInteger(), nullable=True)),
        ("source_domains", sa.Column("first_metrics_at", sa.DateTime(timezone=True), nullable=True)),
        ("source_domains", sa.Column("first_metrics_source", sa.String(12), nullable=True)),
        # Manual enrichment labels (user-set, never recomputed).
        ("source_domains", sa.Column("market", sa.String(80), nullable=True)),
        ("source_domains", sa.Column("country", sa.String(80), nullable=True)),
        # Old/new payload per metric check: {"old": {...}, "new": {...}}.
        ("metric_check_history", sa.Column("values", JSONB(), nullable=True)),
        # Opportunity workflow: who an opportunity domain is assigned to (the
        # existing `reason` VARCHAR(300) column doubles as the note).
        ("competitor_domain_decisions", sa.Column("assigned_to", PGUUID(as_uuid=True), nullable=True)),
    ]


def upgrade() -> None:
    bind = op.get_bind()

    for table, column in _new_columns():
        if not _has_column(bind, table, column.name):
            op.add_column(table, column)

    # Widen decision status: the new vocabulary's longest value
    # ('needs_link_type_review') is 22 chars, over the original VARCHAR(20).
    width = bind.execute(
        sa.text(
            "SELECT character_maximum_length FROM information_schema.columns "
            "WHERE table_name = 'competitor_domain_decisions' AND column_name = 'status'"
        )
    ).scalar()
    if width is not None and width < 30:
        op.alter_column(
            "competitor_domain_decisions",
            "status",
            type_=sa.String(30),
            existing_type=sa.String(20),
            existing_nullable=False,
        )

    # Workspace/time audit index. The table has no created_at (no TimestampMixin);
    # fetched_at is its server-defaulted creation stamp, so it takes that role.
    if not _has_index(bind, "metric_check_history", "ix_metric_check_history_ws"):
        op.create_index(
            "ix_metric_check_history_ws",
            "metric_check_history",
            ["workspace_id", "fetched_at"],
        )


def downgrade() -> None:
    bind = op.get_bind()
    if _has_index(bind, "metric_check_history", "ix_metric_check_history_ws"):
        op.drop_index("ix_metric_check_history_ws", table_name="metric_check_history")
    for table, column in reversed(_new_columns()):
        if _has_column(bind, table, column.name):
            op.drop_column(table, column.name)
    # status stays VARCHAR(30): narrowing back would fail (or truncate) if any
    # row already stores one of the longer workflow statuses.
