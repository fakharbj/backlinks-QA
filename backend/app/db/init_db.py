"""Programmatic schema bootstrap + maintenance helpers.

``init_models`` builds the full schema (enums → tables → partitions → matviews)
without Alembic; the integration test-suite uses it, and the Compose entrypoint
falls back to it if migrations are unavailable. Production uses Alembic.
"""

from __future__ import annotations

import re
from datetime import date

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncEngine

from app.db import ddl
from app.db.base import Base

_MONTH_PART_RE = re.compile(r"_(\d{6})$")  # e.g. crawl_results_202606

# Ensure every model is registered before create_all runs.
import app.models  # noqa: F401,E402


async def init_models(engine: AsyncEngine) -> None:
    async with engine.begin() as conn:
        await conn.execute(text("CREATE EXTENSION IF NOT EXISTS pgcrypto;"))
        for stmt in ddl.create_enum_sql():
            await conn.execute(text(stmt))
        await conn.run_sync(Base.metadata.create_all)
        await conn.execute(text(ddl.PARTITION_FUNCTION_SQL))
        for stmt in ddl.default_partitions_sql():
            await conn.execute(text(stmt))
        for stmt in ddl.rolling_partitions_sql():
            await conn.execute(text(stmt))
        # No materialized views: the dashboard queries backlink_records live.


async def drop_all(engine: AsyncEngine) -> None:
    async with engine.begin() as conn:
        # Drop any legacy matviews that may exist on older databases.
        for name in reversed(ddl.MATVIEW_NAMES):
            await conn.execute(text(f"DROP MATERIALIZED VIEW IF EXISTS {name} CASCADE;"))
        await conn.run_sync(Base.metadata.drop_all)
        for _, name in reversed(ddl.ENUM_TYPES):
            await conn.execute(text(f"DROP TYPE IF EXISTS {name} CASCADE;"))


async def ensure_future_partitions(engine: AsyncEngine, months_forward: int = 3) -> None:
    """Roll partitions forward — called periodically by the maintenance worker."""
    async with engine.begin() as conn:
        for stmt in ddl.rolling_partitions_sql(months_back=0, months_forward=months_forward):
            await conn.execute(text(stmt))


async def drop_partitions_before(engine: AsyncEngine, table: str, cutoff: date) -> list[str]:
    """Drop whole monthly partitions of ``table`` older than ``cutoff``'s month.

    O(1) per partition vs. a row-by-row DELETE over millions of rows. The catch-all
    ``{table}_default`` partition is never dropped.
    """
    cutoff_yyyymm = cutoff.year * 100 + cutoff.month
    dropped: list[str] = []
    async with engine.begin() as conn:
        rows = (
            await conn.execute(
                text(
                    "SELECT child.relname FROM pg_inherits "
                    "JOIN pg_class parent ON parent.oid = pg_inherits.inhparent "
                    "JOIN pg_class child ON child.oid = pg_inherits.inhrelid "
                    "WHERE parent.relname = :t"
                ),
                {"t": table},
            )
        ).all()
        for (name,) in rows:
            m = _MONTH_PART_RE.search(name)
            if not m:
                continue  # skip _default and any non-month partition
            if int(m.group(1)) < cutoff_yyyymm:
                await conn.execute(text(f'DROP TABLE IF EXISTS "{name}"'))
                dropped.append(name)
    return dropped
