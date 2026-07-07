"""Source-domain discovery date — the single "when did this domain enter our
catalog" timestamp that the company dashboard's "new source domains" buckets on.

Discovery = the earliest a domain became a Source Domain by ANY path:
  * our own backlinks  → earliest backlink placement/creation date,
  * a domain import    → when it was approved into the catalog (created_at),
  * a competitor promo → when it was promoted in (created_at).
Computed as LEAST(source_domains.created_at, min(coalesce(placement_date, created_at))
over its backlinks). Backfilled here; kept current by source_domain_service.recompute
and the promotion path.

Revision ID: 0041_source_domain_discovery
Revises: 0040_perf_indexes
Create Date: 2026-07-07
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op

revision = "0041_source_domain_discovery"
down_revision = "0040_perf_indexes"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column("source_domains", sa.Column("discovery_date", sa.DateTime(timezone=True)))
    # Backfill: earliest of the catalog row's created_at and its first backlink's
    # real creation/placement date. LEAST ignores NULL, so catalog-only imported
    # rows (no backlinks) keep their created_at as the discovery date.
    op.execute(
        """
        UPDATE source_domains sd SET discovery_date = LEAST(
            sd.created_at,
            (SELECT min(coalesce(b.placement_date, b.created_at))
               FROM backlink_records b
              WHERE b.workspace_id = sd.workspace_id
                AND b.source_domain = sd.domain_key)
        )
        """
    )
    op.execute("UPDATE source_domains SET discovery_date = created_at WHERE discovery_date IS NULL")
    op.create_index(
        "ix_source_domains_ws_discovery", "source_domains", ["workspace_id", "discovery_date"]
    )


def downgrade() -> None:
    op.drop_index("ix_source_domains_ws_discovery", table_name="source_domains")
    op.drop_column("source_domains", "discovery_date")
