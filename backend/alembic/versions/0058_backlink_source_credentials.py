"""Optional source-site account credentials on a backlink:
backlink_records.source_credentials JSONB ({"login": ..., "password": ...}).

Kept in a dedicated column (never in the serialized ``extra`` bag) so it only
surfaces through the role-gated backlink-detail field. Fed by the task sheet's
Login/Password fill-in columns (and any import carrying Login/Password headers).
Nullable + additive → safe/instant on the existing table.

Revision ID: 0058_backlink_source_credentials
Revises: 0057_intern_role
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision = "0058_backlink_source_credentials"
down_revision = "0057_intern_role"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "backlink_records",
        sa.Column("source_credentials", postgresql.JSONB(astext_type=sa.Text()), nullable=True),
    )


def downgrade() -> None:
    op.drop_column("backlink_records", "source_credentials")
