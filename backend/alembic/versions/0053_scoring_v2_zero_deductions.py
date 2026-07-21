"""Owner scoring change (2026-07-22): zero four deduction groups via a new
GLOBAL rule-set version.

The owner removed these from scoring (the issues stay visible, they just no
longer cost points):
  - Anchor text — Changed           (anchor_match.changed,   was −10)
  - Canonical — Missing             (canonical.missing,      was −3)
  - Link placement — every outcome  (link_placement.header/footer/sidebar/nav,
                                     each was −3)
PQ-06 (adult/gambling/pharma/spam keywords) is unmapped to any parameter, so it
is neutralised in code instead (qa/scoring.py _UNSCORED_CODES) — not here.
link_rel.sponsored deliberately KEEPS its −10: the owner's brief only changes
the status rule (score ≥ warn_below → PASS regardless of severities; that is a
code change in qa/classification.py, also not here).

Mechanically this mirrors scoring_config_service.save_version for the global
scope: retire the current latest global row, insert the next version with the
same rules + the zeros applied. Idempotent — if the latest global rules already
carry all the zeros, nothing is written. Existing links are NOT touched here;
the operator re-scores via POST /scoring/rescore (or the server-side loop).

Revision ID: 0053_scoring_v2_zero_deductions
Revises: 0052_notification_prefs
"""

from __future__ import annotations

import json

import sqlalchemy as sa
from alembic import op

revision = "0053_scoring_v2_zero_deductions"
down_revision = "0052_notification_prefs"
branch_labels = None
depends_on = None

# parameter_key -> outcome keys to zero.
_ZEROS: dict[str, list[str]] = {
    "anchor_match": ["changed"],
    "canonical": ["missing"],
    "link_placement": ["header", "footer", "sidebar", "nav"],
}


def upgrade() -> None:
    bind = op.get_bind()
    row = bind.execute(
        sa.text(
            "SELECT id, version, rules, bands FROM scoring_rule_versions "
            "WHERE scope = 'global' AND workspace_id IS NULL AND scope_ref_id IS NULL "
            "AND link_type_id IS NULL AND is_latest = true "
            "ORDER BY version DESC LIMIT 1"
        )
    ).first()
    if row is None:
        # Fresh install without the 0016/0037 seed — nothing to derive from;
        # the service seeds defaults on first use.
        return

    rules = dict(row.rules or {})
    changed = False
    for param, outcomes in _ZEROS.items():
        cur = dict(rules.get(param) or {})
        for oc in outcomes:
            if cur.get(oc) != 0:
                cur[oc] = 0
                changed = True
        rules[param] = cur
    if not changed:
        return  # already zeroed — idempotent no-op

    next_version = int(row.version) + 1
    bind.execute(
        sa.text(
            "UPDATE scoring_rule_versions SET is_latest = false "
            "WHERE scope = 'global' AND workspace_id IS NULL AND scope_ref_id IS NULL "
            "AND link_type_id IS NULL AND is_latest = true"
        )
    )
    bind.execute(
        sa.text(
            "INSERT INTO scoring_rule_versions "
            "(id, workspace_id, scope, scope_ref_id, link_type_id, version, is_latest, "
            " rules, bands, note, created_by, activated_at, created_at, updated_at) "
            "VALUES (gen_random_uuid(), NULL, 'global', NULL, NULL, :version, true, "
            " CAST(:rules AS jsonb), CAST(:bands AS jsonb), :note, NULL, now(), now(), now())"
        ),
        {
            "version": next_version,
            "rules": json.dumps(rules),
            "bands": json.dumps(dict(row.bands or {"fail_below": 30, "warn_below": 80})),
            "note": "Owner change 2026-07-22: anchor-changed / canonical-missing / all link-placement deductions zeroed (0053)",
        },
    )


def downgrade() -> None:
    # Re-activate the previous global version and drop the 0053 row. Only safe
    # immediately after upgrade; historical crawl_results keep their stamped
    # version ids either way.
    bind = op.get_bind()
    bind.execute(
        sa.text(
            "DELETE FROM scoring_rule_versions WHERE scope = 'global' "
            "AND workspace_id IS NULL AND note LIKE '%(0053)%'"
        )
    )
    bind.execute(
        sa.text(
            "UPDATE scoring_rule_versions SET is_latest = true "
            "WHERE scope = 'global' AND workspace_id IS NULL AND scope_ref_id IS NULL "
            "AND link_type_id IS NULL AND version = ("
            "  SELECT max(version) FROM scoring_rule_versions WHERE scope = 'global' "
            "  AND workspace_id IS NULL AND scope_ref_id IS NULL AND link_type_id IS NULL)"
        )
    )
