"""Case-insensitive uniqueness for login emails.

Every write path already lowercases emails (auth register, team invite, sheet
auto-provision, account edit), but the DB itself only had a case-SENSITIVE
unique on ``users.email`` — a mixed-case duplicate slipping in through any
future path would create two logins for one person. This functional unique
index makes ``Junius@x.com`` vs ``junius@x.com`` a hard conflict at the
database layer (brief §13: capitalization-only duplicate accounts must be
impossible).

Revision ID: 0051_email_ci_unique
Revises: 0050_skipped_rows
"""

from __future__ import annotations

from alembic import op

revision = "0051_email_ci_unique"
down_revision = "0050_skipped_rows"
branch_labels = None
depends_on = None


def upgrade() -> None:
    # Normalize any legacy mixed-case emails first (idempotent; write paths
    # already lowercase, so collisions here would mean true duplicates — the
    # WHERE guard skips rows whose lowercase form is already taken so the
    # migration never destroys a login; such pairs surface in Data health).
    op.execute(
        """
        UPDATE users u SET email = lower(email)
        WHERE email <> lower(email)
          AND NOT EXISTS (SELECT 1 FROM users d WHERE d.email = lower(u.email))
        """
    )
    # Refuse loudly (with the offending addresses) if true case-duplicates
    # exist — an operator must merge those accounts, not a migration.
    dupes = op.get_bind().exec_driver_sql(
        "SELECT lower(email) FROM users GROUP BY lower(email) HAVING count(*) > 1"
    ).fetchall()
    if dupes:
        raise RuntimeError(
            "Cannot enforce case-insensitive email uniqueness — duplicate "
            f"accounts differ only by case: {', '.join(d[0] for d in dupes)}. "
            "Merge/remove them in Team settings, then re-run the migration."
        )
    op.execute(
        "CREATE UNIQUE INDEX IF NOT EXISTS uq_users_email_lower ON users (lower(email))"
    )


def downgrade() -> None:
    op.execute("DROP INDEX IF EXISTS uq_users_email_lower")
