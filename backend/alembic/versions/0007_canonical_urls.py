"""Canonical URLs + fingerprint identity layer (Phase 8, feature 8).

Adds the global ``canonical_urls`` table (``fingerprint`` = sha256 of the canonical/
normalized URL, unique-indexed) and a ``backlink_records.canonical_url_id`` column,
then backfills both from the existing ``source_url_normalized`` values so the
identity layer is populated immediately after upgrade.

Additive + idempotent (``IF NOT EXISTS`` / ``ON CONFLICT DO NOTHING``). Nothing
reads ``canonical_url_id`` yet — wiring into import + duplicate/conflict detection
lands in a later migration — so applying this changes no runtime behaviour.

Revision ID: 0007_canonical_urls
Revises: 0006_report_versioning
Create Date: 2026-06-26
"""

from __future__ import annotations

from alembic import op

# Register models on Base.metadata.
import app.models  # noqa: F401,E402
from app.models.canonical_url import CanonicalUrl

revision = "0007_canonical_urls"
down_revision = "0006_report_versioning"
branch_labels = None
depends_on = None


def upgrade() -> None:
    bind = op.get_bind()
    op.execute("CREATE EXTENSION IF NOT EXISTS pgcrypto;")  # for digest()

    CanonicalUrl.__table__.create(bind=bind, checkfirst=True)

    op.execute(
        "ALTER TABLE backlink_records ADD COLUMN IF NOT EXISTS canonical_url_id uuid"
    )
    op.execute(
        "CREATE INDEX IF NOT EXISTS ix_backlink_records_canonical_url "
        "ON backlink_records (canonical_url_id)"
    )

    # ── Backfill canonical_urls from existing normalized source URLs ──────────
    # fingerprint = sha256(source_url_normalized); source_url_normalized was already
    # produced by crawler.normalize, so it matches what the service will compute.
    op.execute(
        """
        INSERT INTO canonical_urls (
            id, fingerprint, canonical_url, sample_url, registrable_domain,
            total_uses, first_seen_at, last_seen_at, created_at, updated_at)
        SELECT gen_random_uuid(),
            encode(digest(source_url_normalized, 'sha256'), 'hex'),
            source_url_normalized,
            min(source_page_url),
            max(source_domain),
            count(*),
            min(created_at), max(created_at), now(), now()
        FROM backlink_records
        WHERE source_url_normalized IS NOT NULL AND source_url_normalized <> ''
        GROUP BY source_url_normalized
        ON CONFLICT (fingerprint) DO NOTHING;
        """
    )
    op.execute(
        """
        UPDATE backlink_records b
        SET canonical_url_id = cu.id
        FROM canonical_urls cu
        WHERE cu.fingerprint = encode(digest(b.source_url_normalized, 'sha256'), 'hex')
          AND b.canonical_url_id IS NULL;
        """
    )


def downgrade() -> None:
    op.execute("DROP INDEX IF EXISTS ix_backlink_records_canonical_url")
    op.execute("ALTER TABLE backlink_records DROP COLUMN IF EXISTS canonical_url_id")
    op.execute("DROP TABLE IF EXISTS canonical_urls CASCADE;")
