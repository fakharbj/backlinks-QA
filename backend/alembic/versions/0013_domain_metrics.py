"""Per-domain metrics on source_domains (Phase 8, features 21/22/23).

Adds Moz (da/pa/spam), Semrush (authority score/traffic/keywords) and domain-age
columns to ``source_domains``, populated per domain by
``source_domain_service.fetch_metrics``. Additive + idempotent.

Revision ID: 0013_domain_metrics
Revises: 0012_source_domains
Create Date: 2026-06-26
"""

from __future__ import annotations

from alembic import op

revision = "0013_domain_metrics"
down_revision = "0012_source_domains"
branch_labels = None
depends_on = None

_COLUMNS = [
    "da integer",
    "pa integer",
    "spam_score integer",
    "semrush_as integer",
    "semrush_traffic bigint",
    "semrush_keywords integer",
    "domain_created_on date",
    "domain_age_days integer",
    "metrics_updated_at timestamptz",
]


def upgrade() -> None:
    for col in _COLUMNS:
        op.execute(f"ALTER TABLE source_domains ADD COLUMN IF NOT EXISTS {col}")


def downgrade() -> None:
    for col in _COLUMNS:
        name = col.split()[0]
        op.execute(f"ALTER TABLE source_domains DROP COLUMN IF EXISTS {name}")
