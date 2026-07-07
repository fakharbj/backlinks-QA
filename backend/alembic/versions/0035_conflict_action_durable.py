"""Make backlink_conflict_actions an append-only audit log that outlives groups.

0034 created ``backlink_conflict_actions.conflict_id`` with a CASCADE foreign key
to ``backlink_conflicts``. But keep-one / bulk-resolve legitimately DELETE the
group, which cascade-wiped its own action history — the opposite of an audit log.
Drop the FK (keep the plain uuid column) so the history survives group deletion;
the actions endpoint scopes reads by ``workspace_id`` instead.

Revision ID: 0035_conflict_action_durable
Revises: 0034_duplicate_enterprise
Create Date: 2026-07-07
"""

from __future__ import annotations

from alembic import op

revision = "0035_conflict_action_durable"
down_revision = "0034_duplicate_enterprise"
branch_labels = None
depends_on = None

_FK = "fk_backlink_conflict_actions_conflict_id_backlink_conflicts"


def upgrade() -> None:
    op.execute(f"ALTER TABLE backlink_conflict_actions DROP CONSTRAINT IF EXISTS {_FK}")


def downgrade() -> None:
    # NOT VALID: existing rows may reference already-deleted groups.
    op.execute(
        f"ALTER TABLE backlink_conflict_actions ADD CONSTRAINT {_FK} "
        "FOREIGN KEY (conflict_id) REFERENCES backlink_conflicts(id) "
        "ON DELETE CASCADE NOT VALID"
    )
