"""Canonical URL + fingerprint resolution (Phase 8, feature 8).

The pure helpers (``canonical_form``, ``fingerprint_for``, ``fingerprint_of_raw``)
are unit-tested without a DB. ``resolve_canonical`` get-or-creates the
``canonical_urls`` row by fingerprint (idempotent, concurrency-safe via
INSERT … ON CONFLICT), returning the row so callers can attach ``canonical_url_id``.

Canonicalisation reuses ``crawler.normalize.normalize_url`` so the fingerprint of a
freshly-canonicalised URL matches the fingerprint backfilled from the stored
``source_url_normalized`` (which was produced by the same normaliser at import).
"""

from __future__ import annotations

import hashlib
import uuid
from datetime import datetime, timezone

from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.ext.asyncio import AsyncSession

from app.crawler.normalize import normalize_url
from app.models.canonical_url import CanonicalUrl


def canonical_form(raw_url: str) -> str | None:
    """Return the canonical match form of a URL, or ``None`` if it isn't a web URL."""
    parsed = normalize_url(raw_url)
    return parsed.normalized if parsed.valid else None


def fingerprint_for(canonical_url: str) -> str:
    """SHA-256 hex digest (64 chars) of a canonical URL string."""
    return hashlib.sha256(canonical_url.encode("utf-8")).hexdigest()


def fingerprint_of_raw(raw_url: str) -> str | None:
    """Canonicalise then fingerprint a raw URL; ``None`` if the URL is invalid."""
    canon = canonical_form(raw_url)
    return fingerprint_for(canon) if canon is not None else None


async def resolve_canonical(
    db: AsyncSession,
    raw_url: str,
    *,
    cache: dict[str, uuid.UUID] | None = None,
) -> CanonicalUrl | None:
    """Get-or-create the :class:`CanonicalUrl` for ``raw_url``.

    Idempotent: a second call for the same page reuses the existing row and only
    bumps ``last_seen_at``. Returns ``None`` for invalid/unsupported URLs.
    """
    parsed = normalize_url(raw_url)
    if not parsed.valid:
        return None
    canon = parsed.normalized
    fp = fingerprint_for(canon)

    if cache is not None and fp in cache:
        return await db.get(CanonicalUrl, cache[fp])

    now = datetime.now(timezone.utc)
    stmt = (
        pg_insert(CanonicalUrl)
        .values(
            fingerprint=fp,
            canonical_url=canon,
            sample_url=raw_url[:2048],
            registrable_domain=parsed.registrable_domain or None,
            total_uses=0,
            first_seen_at=now,
            last_seen_at=now,
        )
        # Identity already exists → just touch last_seen_at (counts are reconciled
        # separately so they never drift on re-syncs).
        .on_conflict_do_update(index_elements=["fingerprint"], set_={"last_seen_at": now})
        .returning(CanonicalUrl.id)
    )
    canonical_id = (await db.execute(stmt)).scalar_one()
    if cache is not None:
        cache[fp] = canonical_id
    return await db.get(CanonicalUrl, canonical_id)
