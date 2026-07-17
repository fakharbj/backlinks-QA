"""Temp QA lab — candidate submission fields (Phase 11.1).

Real candidate sheets carry, per link: the account email + password they made,
the DA and Spam Score they CLAIM, and some rows are "competitor" references
(no link to QA). Capture all of it so a reviewer sees claimed-vs-measured and
the login details, and competitor rows are recorded separately.

Revision ID: 0049_qa_test_submission_fields
Revises: 0048_qa_test_lab
Create Date: 2026-07-18
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op

revision = "0049_qa_test_submission_fields"
down_revision = "0048_qa_test_lab"
branch_labels = None
depends_on = None


def _has_col(bind, table: str, col: str) -> bool:
    return bind.execute(
        sa.text(
            "SELECT 1 FROM information_schema.columns "
            "WHERE table_name=:t AND column_name=:c"
        ),
        {"t": table, "c": col},
    ).first() is not None


def upgrade() -> None:
    bind = op.get_bind()
    cols = [
        ("account_email", "VARCHAR(255)"),
        ("account_password", "VARCHAR(255)"),
        ("claimed_da", "INTEGER"),
        ("claimed_spam", "INTEGER"),
        ("is_competitor", "BOOLEAN NOT NULL DEFAULT false"),
    ]
    for name, ddl in cols:
        if not _has_col(bind, "qa_test_links", name):
            op.execute(f"ALTER TABLE qa_test_links ADD COLUMN {name} {ddl}")
    # The candidate's original task brief, kept on the batch for reference.
    if not _has_col(bind, "qa_test_batches", "brief"):
        op.execute("ALTER TABLE qa_test_batches ADD COLUMN brief TEXT NULL")


def downgrade() -> None:
    for name in ("account_email", "account_password", "claimed_da", "claimed_spam", "is_competitor"):
        op.execute(f"ALTER TABLE qa_test_links DROP COLUMN IF EXISTS {name}")
    op.execute("ALTER TABLE qa_test_batches DROP COLUMN IF EXISTS brief")
