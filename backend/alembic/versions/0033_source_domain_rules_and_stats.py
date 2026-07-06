"""Stored qualified/referring counts on source_domains + source_domain_rules.

Adds STORED per-domain QA-outcome counters to ``source_domains`` (mirrors the
existing index/dofollow counters — refreshed set-based by
``source_domain_service.recompute``), the metric-sort composite indexes the
Source-Domains desk needs, and a new ``source_domain_rules`` table for saved,
shareable domain-qualification rule definitions.

The new counters are backfilled set-based so existing rows are correct the
moment this migration runs (no recompute required). Outcome buckets use the
EFFECTIVE status (``coalesce(override_status, status)``), matching the app's
``effective_status``. ``OverallStatus`` literals: PASS / WARNING / FAIL /
PENDING (see ``app.qa.enums``). ``backlink_records`` has ``override_status``,
``status`` and ``target_domain`` columns (confirmed on the model).

Revision ID: 0033_source_domain_rules_and_stats
Revises: 0032_post_reset_repair
Create Date: 2026-07-07
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision = "0033_source_domain_rules"  # <=32 chars (alembic_version.version_num is varchar(32))
down_revision = "0032_post_reset_repair"
branch_labels = None
depends_on = None


_NEW_COUNTERS = (
    "qualified_count",
    "not_qualified_count",
    "warning_count",
    "fail_count",
    "pending_count",
    "referring_domains_count",
)

_NEW_INDEXES = (
    ("ix_source_domains_ws_da", ("workspace_id", "da")),
    ("ix_source_domains_ws_pa", ("workspace_id", "pa")),
    ("ix_source_domains_ws_spam", ("workspace_id", "spam_score")),
    ("ix_source_domains_ws_as", ("workspace_id", "semrush_as")),
    ("ix_source_domains_ws_qualified", ("workspace_id", "qualified_count")),
)


def upgrade() -> None:
    # ── 1. New stored counters on source_domains ─────────────────────────────
    for col in _NEW_COUNTERS:
        op.add_column(
            "source_domains",
            sa.Column(col, sa.Integer(), nullable=False, server_default="0"),
        )

    # ── 2. Metric-sort composite indexes ─────────────────────────────────────
    for name, cols in _NEW_INDEXES:
        op.create_index(name, "source_domains", list(cols))

    # ── 3. source_domain_rules table ─────────────────────────────────────────
    op.create_table(
        "source_domain_rules",
        sa.Column(
            "id",
            postgresql.UUID(as_uuid=True),
            primary_key=True,
            server_default=sa.text("gen_random_uuid()"),
        ),
        sa.Column(
            "workspace_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("workspaces.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column(
            "project_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("projects.id", ondelete="CASCADE"),
            nullable=True,
        ),
        sa.Column("name", sa.String(length=150), nullable=False),
        sa.Column("description", sa.String(length=500), nullable=True),
        sa.Column(
            "definition",
            postgresql.JSONB(),
            nullable=False,
            server_default=sa.text("'{}'::jsonb"),
        ),
        sa.Column(
            "is_shared",
            sa.Boolean(),
            nullable=False,
            server_default=sa.text("true"),
        ),
        sa.Column("created_by", postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column("updated_by", postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.UniqueConstraint(
            "workspace_id",
            "project_id",
            "name",
            name="uq_source_domain_rules_ws_proj_name",
        ),
    )
    op.create_index(
        "ix_source_domain_rules_ws",
        "source_domain_rules",
        ["workspace_id", "project_id"],
    )

    # ── 4. Backfill the new counters set-based (effective status) ─────────────
    # Effective status = coalesce(override_status, status); qualified == PASS.
    op.execute(
        """
        UPDATE source_domains sd SET
            qualified_count = x.q,
            not_qualified_count = x.nq,
            warning_count = x.w,
            fail_count = x.f,
            pending_count = x.p,
            referring_domains_count = x.rd
        FROM (
            SELECT
                workspace_id,
                source_domain,
                count(*) FILTER (WHERE coalesce(override_status, status)::text = 'PASS') AS q,
                count(*) FILTER (WHERE coalesce(override_status, status)::text = 'WARNING') AS w,
                count(*) FILTER (WHERE coalesce(override_status, status)::text = 'FAIL') AS f,
                count(*) FILTER (WHERE coalesce(override_status, status)::text = 'PENDING') AS p,
                count(*) FILTER (WHERE coalesce(override_status, status)::text <> 'PASS') AS nq,
                count(DISTINCT target_domain) AS rd
            FROM backlink_records
            WHERE source_domain IS NOT NULL AND source_domain <> ''
            GROUP BY workspace_id, source_domain
        ) x
        WHERE sd.workspace_id = x.workspace_id AND sd.domain_key = x.source_domain;
        """
    )


def downgrade() -> None:
    op.drop_index("ix_source_domain_rules_ws", table_name="source_domain_rules")
    op.drop_table("source_domain_rules")

    for name, _cols in _NEW_INDEXES:
        op.drop_index(name, table_name="source_domains")

    for col in reversed(_NEW_COUNTERS):
        op.drop_column("source_domains", col)
