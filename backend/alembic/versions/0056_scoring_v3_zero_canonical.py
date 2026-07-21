"""Owner scoring change (2026-07-22 #2): ignore ALL canonical issues.

Global rule-set v3: canonical.mismatch (was −25) and canonical.cross_domain
(was −60) → 0 (canonical.missing was already zeroed in 0053). The rule-set
zeroing keeps the Scoring desk truthful; the authoritative neutralisation for
stored snapshots lives in code (qa/scoring.py _UNSCORED_CODES += CAN-* — which
also disarms CAN-04's CRITICAL score-cap — and qa/classification.py excludes
CAN-* from definite_critical so a cross-domain canonical no longer forces
FAIL). Existing links are re-scored by the operator afterwards.

Same idempotent mechanics as 0053.

Revision ID: 0056_scoring_v3_zero_canonical
Revises: 0055_user_avatar
"""

from __future__ import annotations

import json

import sqlalchemy as sa
from alembic import op

revision = "0056_scoring_v3_zero_canonical"
down_revision = "0055_user_avatar"
branch_labels = None
depends_on = None

_ZEROS: dict[str, list[str]] = {
    "canonical": ["missing", "mismatch", "cross_domain"],
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
        return

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
            "note": "Owner change 2026-07-22: ALL canonical deductions zeroed (0056)",
        },
    )


def downgrade() -> None:
    bind = op.get_bind()
    bind.execute(
        sa.text(
            "DELETE FROM scoring_rule_versions WHERE scope = 'global' "
            "AND workspace_id IS NULL AND note LIKE '%(0056)%'"
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
