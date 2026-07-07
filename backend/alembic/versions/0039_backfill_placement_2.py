"""Second placement_date backfill pass — 2-digit-year formats (e.g. "01-Nov-24").

0038 filled month-name dates; a small tail used 2-digit years the parser didn't
accept yet. The parser now handles them; this re-runs the same idempotent backfill
(only touches rows still NULL) to catch the stragglers.

Revision ID: 0039_backfill_placement2
Revises: 0038_backfill_placement
Create Date: 2026-07-07
"""

from __future__ import annotations

from datetime import date, datetime

from alembic import op
from sqlalchemy import text

revision = "0039_backfill_placement2"
down_revision = "0038_backfill_placement"
branch_labels = None
depends_on = None

_FORMATS = (
    "%Y-%m-%d", "%d/%m/%Y", "%m/%d/%Y", "%d-%m-%Y", "%Y/%m/%d",
    "%d-%B-%Y", "%d %B %Y", "%B %d, %Y", "%B %d %Y",
    "%d-%b-%Y", "%d %b %Y", "%b %d, %Y", "%b %d %Y",
    "%d.%m.%Y", "%Y.%m.%d",
    "%d-%b-%y", "%d-%B-%y", "%d/%m/%y", "%m/%d/%y", "%d %b %y",
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
    updates = [{"bid": r["bid"], "d": d} for r in rows if (d := _parse(r["src"])) is not None]
    upd = text(
        "UPDATE backlink_records SET placement_date = :d "
        "WHERE id = :bid AND placement_date IS NULL"
    )
    for i in range(0, len(updates), 1000):
        bind.execute(upd, updates[i : i + 1000])


def downgrade() -> None:
    pass
