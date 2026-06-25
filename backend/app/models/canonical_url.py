"""Canonical URLs + SHA-256 fingerprint (Phase 8, feature 8).

Every monitored URL collapses to a single canonical identity. The canonical form
is produced by ``crawler.normalize.normalize_url`` (https-pinned, ``www`` stripped,
tracking params dropped, fragment dropped, IDN→punycode, lenient trailing slash);
its SHA-256 hex digest is the ``fingerprint``.

This is a **global** table (no ``workspace_id``) — the same page is one identity
everywhere — so a duplicate check is an O(log n) unique-index seek rather than a
sequential scan. Backlinks (and, later, competitor backlinks) reference it via
``canonical_url_id``; duplicate/conflict *scoping* stays per-workspace on the
referencing rows, so tenants never see each other's data.
"""

from __future__ import annotations

from datetime import datetime

from sqlalchemy import DateTime, Integer, String
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base, TimestampMixin, UUIDPrimaryKeyMixin


class CanonicalUrl(UUIDPrimaryKeyMixin, TimestampMixin, Base):
    __tablename__ = "canonical_urls"

    # sha256 hex of the canonical URL (64 chars). The single most important index
    # in the system: turns duplicate detection into a B-tree seek (~19 comparisons
    # at 500k rows, still <2ms at 5M).
    fingerprint: Mapped[str] = mapped_column(String(64), nullable=False, unique=True)
    canonical_url: Mapped[str] = mapped_column(String(2048), nullable=False)
    sample_url: Mapped[str | None] = mapped_column(String(2048))  # an example raw URL
    registrable_domain: Mapped[str | None] = mapped_column(String(255), index=True)
    # Best-effort reference count; the source of truth is the number of backlinks
    # pointing here. Maintained by the backfill + (later) the reconcile job, not on
    # every resolve, so it never drifts on re-syncs.
    total_uses: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    first_seen_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    last_seen_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
