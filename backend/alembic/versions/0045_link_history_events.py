"""Complete per-link history events (Phase 10 P5).

Two additive pieces:

* ``backlink_history`` gains actor/provenance columns (``actor_user_id``,
  ``actor_role``, ``source``, ``note``) so manual actions (create/edit/override/
  reassign/delete/rescore/…) carry WHO did them and from WHERE. The table is
  RANGE-partitioned by ``created_at`` — the ``ALTER TABLE`` targets the
  PARTITIONED PARENT only; PG16 propagates column adds to every partition
  (including ``backlink_history_default``) automatically.
* ``history_event_type_enum`` (native pg enum) gains the manual/action values.
  Postgres 12+ allows ADD VALUE inside a transaction as long as the new values
  aren't used in the same migration (they aren't). Idempotent via IF NOT EXISTS
  (same pattern as 0018).

Downgrade drops the columns; enum values cannot be removed individually in
Postgres — leaving them is harmless (mirrors 0018).

Revision ID: 0045_link_history_events
Revises: 0044_domain_enrichment
Create Date: 2026-07-11
"""

from __future__ import annotations

from alembic import op

revision = "0045_link_history_events"
down_revision = "0044_domain_enrichment"
branch_labels = None
depends_on = None

# (column name, SQL type) — additive + nullable, so existing rows are untouched.
_COLUMNS = (
    ("actor_user_id", "uuid"),
    ("actor_role", "varchar(20)"),
    ("source", "varchar(12)"),  # ui | sheet | import | worker | system
    ("note", "varchar(300)"),
)

_EVENT_VALUES = (
    "created",
    "edited",
    "override_set",
    "override_cleared",
    "reassigned",
    "link_type_changed",
    "deleted",
    "recheck_requested",
    "rescored",
    "index_status_changed",
    "metrics_changed",
    "dedup_status_changed",
)


def upgrade() -> None:
    # Idempotent: IF NOT EXISTS guards a re-run on a partially-migrated box.
    for name, sql_type in _COLUMNS:
        op.execute(
            f"ALTER TABLE backlink_history ADD COLUMN IF NOT EXISTS {name} {sql_type}"
        )
    for value in _EVENT_VALUES:
        op.execute(f"ALTER TYPE history_event_type_enum ADD VALUE IF NOT EXISTS '{value}'")


def downgrade() -> None:
    for name, _ in reversed(_COLUMNS):
        op.execute(f"ALTER TABLE backlink_history DROP COLUMN IF EXISTS {name}")
    # Postgres cannot drop a single enum value; leaving the values is harmless.
