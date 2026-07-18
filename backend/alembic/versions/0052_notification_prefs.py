"""Per-user notification preferences.

One JSONB blob per login: {category: {enabled, channel, cadence}}. Absent
keys fall back to the category defaults in ``notification_service.CATEGORIES``
(everything on, in-app, immediate). Security notifications are mandatory —
the API refuses to disable them, so the column never needs to encode that.

Revision ID: 0052_notification_prefs
Revises: 0051_email_ci_unique
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects.postgresql import JSONB

revision = "0052_notification_prefs"
down_revision = "0051_email_ci_unique"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "users",
        sa.Column(
            "notification_prefs", JSONB, nullable=False, server_default=sa.text("'{}'::jsonb")
        ),
    )


def downgrade() -> None:
    op.drop_column("users", "notification_prefs")
