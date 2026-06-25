"""Wire the dynamic scoring engine (Phase 8 F17 incr.2).

Additive + idempotent:
* add ``backlink_records.scoring_rule_version_id`` (which rule set produced the
  current denormalised verdict);
* reset the seeded system-global **v1** to empty overrides (``rules = {}``) so it
  is a pure "use the standard severity model" baseline — the QA engine falls back
  to ``severity.deduction`` for any parameter the rule set does not override, which
  reproduces today's scores exactly (guaranteed by the golden test);
* align a couple of registry display-defaults with the actual check severities
  (5xx and 403 are HIGH = -25, not -60/0) so the editable grid is honest.

Revision ID: 0017_scoring_engine_wire
Revises: 0016_dynamic_scoring
Create Date: 2026-06-26
"""

from __future__ import annotations

from alembic import op

import app.models  # noqa: F401,E402

revision = "0017_scoring_engine_wire"
down_revision = "0016_dynamic_scoring"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute(
        "ALTER TABLE backlink_records ADD COLUMN IF NOT EXISTS scoring_rule_version_id uuid"
    )
    # Global v1 = pure baseline (no overrides → severity model → today's scores).
    op.execute(
        "UPDATE scoring_rule_versions SET rules = '{}'::jsonb "
        "WHERE scope = 'global' AND version = 1"
    )
    # Honest display defaults for the grid (engine already uses severity for these).
    op.execute(
        """
        UPDATE scoring_parameters
        SET default_points = jsonb_set(
            jsonb_set(default_points, '{server_error}', '-25'::jsonb, true),
            '{forbidden}', '-25'::jsonb, true)
        WHERE key = 'source_http'
        """
    )


def downgrade() -> None:
    op.execute("ALTER TABLE backlink_records DROP COLUMN IF EXISTS scoring_rule_version_id")
