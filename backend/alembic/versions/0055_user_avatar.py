"""Self-service profile photo: users.avatar_data_uri (small data:image/... URI,
same storage pattern as the branding logo). Part of delivery-polish T2 —
owner: users manage their own photo + password.

Revision ID: 0055_user_avatar
Revises: 0054_batch_parent_backfill
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op

revision = "0055_user_avatar"
down_revision = "0054_batch_parent_backfill"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column("users", sa.Column("avatar_data_uri", sa.Text(), nullable=True))


def downgrade() -> None:
    op.drop_column("users", "avatar_data_uri")
