"""Link-type merge/alias layer (Phase 10 P1).

The catalog accumulated ~72 raw names for ~20 real link types (misspellings,
case/plural/abbreviation variants) mirrored in sheet tab names. ``merged_into_id``
turns a catalog row into an ALIAS: when set (always together with ``deleted_at``),
the row is a merged-away variant that redirects to the surviving master —
``resolve_or_create`` follows the chain so a sheet still carrying the old tab name
resolves (and re-labels) to the master instead of resurrecting the duplicate.
NULL = the type is its own master (unmerged). Additive/nullable: existing rows
unchanged. All data repointing runs in link_type_merge_service (needs the Google
tab-rename side effect + an advisory lock), never in raw alembic.

Revision ID: 0043_link_type_merge
Revises: 0042_mapping_canonical_label
Create Date: 2026-07-11
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects.postgresql import UUID as PGUUID

revision = "0043_link_type_merge"
down_revision = "0042_mapping_canonical_label"
branch_labels = None
depends_on = None


def upgrade() -> None:
    # Idempotent: guard against a re-run on a partially-migrated box.
    bind = op.get_bind()
    exists = bind.execute(
        sa.text(
            "SELECT 1 FROM information_schema.columns "
            "WHERE table_name='link_types' AND column_name='merged_into_id'"
        )
    ).first()
    if exists:
        return
    op.add_column(
        "link_types",
        sa.Column(
            "merged_into_id",
            PGUUID(as_uuid=True),
            sa.ForeignKey("link_types.id", ondelete="SET NULL"),
            nullable=True,
        ),
    )
    op.create_index(
        "ix_link_types_merged_into", "link_types", ["merged_into_id"],
        postgresql_where=sa.text("merged_into_id IS NOT NULL"),
    )


def downgrade() -> None:
    op.drop_index("ix_link_types_merged_into", table_name="link_types")
    op.drop_column("link_types", "merged_into_id")
