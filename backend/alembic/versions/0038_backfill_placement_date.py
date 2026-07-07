"""Backfill placement_date (real backlink creation date) from the import rows.

The production sheets supply the backlink's live/placement date in month-name
formats like "30-April-2026", which the old date parser didn't accept — so 96% of
``backlink_records.placement_date`` were left NULL and performance/task-completion
fell back to the import date. The parser is now fixed; this repairs history by
re-parsing each backlink's stored import-row date and filling placement_date where
it is still NULL (never overwrites an existing value).

Revision ID: 0038_backfill_placement
Revises: 0037_reseed_scoring
Create Date: 2026-07-07
"""

from __future__ import annotations

from datetime import date, datetime

from alembic import op
from sqlalchemy import text

revision = "0038_backfill_placement"
down_revision = "0037_reseed_scoring"
branch_labels = None
depends_on = None

# Mirrors import_service._DATE_FORMATS (kept inline so the migration is self-contained).
_FORMATS = (
    "%Y-%m-%d", "%d/%m/%Y", "%m/%d/%Y", "%d-%m-%Y", "%Y/%m/%d",
    "%d-%B-%Y", "%d %B %Y", "%B %d, %Y", "%B %d %Y",
    "%d-%b-%Y", "%d %b %Y", "%b %d, %Y", "%b %d %Y",
    "%d.%m.%Y", "%Y.%m.%d",
)


def _parse(value) -> date | None:
    if not value:
        return None
    raw = str(value).strip()
    for fmt in _FORMATS:
        try:
            return datetime.strptime(raw, fmt).date()
        except ValueError:
            continue
    try:
        return datetime.fromisoformat(raw).date()
    except ValueError:
        return None


def upgrade() -> None:
    bind = op.get_bind()
    rows = bind.execute(
        text(
            """
            SELECT DISTINCT ON (b.id) b.id AS bid,
                   coalesce(nullif(ir.mapped->>'placement_date', ''), ir.raw->>'Date') AS src
            FROM backlink_records b
            JOIN import_rows ir ON ir.backlink_id = b.id
            WHERE b.placement_date IS NULL
              AND coalesce(nullif(ir.mapped->>'placement_date', ''), ir.raw->>'Date') IS NOT NULL
            ORDER BY b.id, ir.id DESC
            """
        )
    ).mappings().all()

    updates = []
    for r in rows:
        d = _parse(r["src"])
        if d is not None:
            updates.append({"bid": r["bid"], "d": d})

    upd = text(
        "UPDATE backlink_records SET placement_date = :d "
        "WHERE id = :bid AND placement_date IS NULL"
    )
    for i in range(0, len(updates), 1000):
        bind.execute(upd, updates[i : i + 1000])


def downgrade() -> None:
    # Data repair only — leaving the backfilled dates is safe.
    pass
