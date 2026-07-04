"""task_week_templates.id needs the standard gen_random_uuid() server default
(every UUIDPrimaryKeyMixin table has it; 0027 missed it).

Revision ID: 0028_template_id_default
Revises: 0027_templates_layoff
Create Date: 2026-07-05
"""

from __future__ import annotations

from alembic import op

revision = "0028_template_id_default"
down_revision = "0027_templates_layoff"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute(
        "ALTER TABLE task_week_templates ALTER COLUMN id SET DEFAULT gen_random_uuid()"
    )


def downgrade() -> None:
    op.execute("ALTER TABLE task_week_templates ALTER COLUMN id DROP DEFAULT")
