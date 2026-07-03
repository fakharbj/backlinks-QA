"""Scale indexes for the Phase-9 hot paths (few-ms at millions of rows).

Every analytical query added in Phase 9 must stay index-bound as data grows:

* ``(project_id, source_domain, created_at)`` — the "first-ever domain in this
  project" NOT-EXISTS probe (project-new counters) becomes an O(log n) index
  lookup per row instead of a scan; also powers the project domain view.
* ``(workspace_id, source_domain, created_at)`` — same for global-new.
* ``(workspace_id, created_at)`` — trends / performance / activity windows.
* ``(workspace_id, assigned_user_label, created_at)`` — per-user performance
  windows and task-day actuals.
* ``(workspace_id, last_checked_at)`` — "recheck older than N days" selection.
* ``(workspace_id, detected_at)`` on conflicts — duplicate trend + new/previous.

NOTE for very large deployments: run these with CREATE INDEX CONCURRENTLY from
psql instead (Alembic runs inside a transaction, which locks writes during the
build). At current data size the plain build is instantaneous.

Revision ID: 0025_scale_indexes
Revises: 0024_project_linktype_scoring
Create Date: 2026-07-04
"""

from __future__ import annotations

from alembic import op

revision = "0025_scale_indexes"
down_revision = "0024_project_linktype_scoring"
branch_labels = None
depends_on = None

_INDEXES = (
    ("ix_bl_project_domain_created", "backlink_records", "(project_id, source_domain, created_at)"),
    ("ix_bl_ws_domain_created", "backlink_records", "(workspace_id, source_domain, created_at)"),
    ("ix_bl_ws_created", "backlink_records", "(workspace_id, created_at)"),
    ("ix_bl_ws_user_created", "backlink_records", "(workspace_id, assigned_user_label, created_at)"),
    ("ix_bl_ws_last_checked", "backlink_records", "(workspace_id, last_checked_at)"),
    ("ix_conflicts_ws_detected", "backlink_conflicts", "(workspace_id, detected_at)"),
)


def upgrade() -> None:
    for name, table, cols in _INDEXES:
        op.execute(f"CREATE INDEX IF NOT EXISTS {name} ON {table} {cols}")


def downgrade() -> None:
    for name, _table, _cols in _INDEXES:
        op.execute(f"DROP INDEX IF EXISTS {name}")
