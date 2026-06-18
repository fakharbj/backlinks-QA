"""Programmatic schema bootstrap + maintenance helpers.

``init_models`` builds the full schema (enums → tables → partitions → matviews)
without Alembic; the integration test-suite uses it, and the Compose entrypoint
falls back to it if migrations are unavailable. Production uses Alembic.
"""

from __future__ import annotations

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncEngine

from app.db import ddl
from app.db.base import Base

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
        for stmt in (s.strip() for s in ddl.MATVIEWS_SQL.split(";")):
            if stmt:
                await conn.execute(text(stmt))


async def drop_all(engine: AsyncEngine) -> None:
    async with engine.begin() as conn:
        for name in reversed(ddl.MATVIEW_NAMES):
            await conn.execute(text(f"DROP MATERIALIZED VIEW IF EXISTS {name} CASCADE;"))
        await conn.run_sync(Base.metadata.drop_all)
        for _, name in reversed(ddl.ENUM_TYPES):
            await conn.execute(text(f"DROP TYPE IF EXISTS {name} CASCADE;"))


async def refresh_matviews(engine: AsyncEngine, *, concurrently: bool = True) -> None:
    async with engine.begin() as conn:
        for stmt in ddl.refresh_matviews_sql(concurrently=concurrently):
            await conn.execute(text(stmt))


async def ensure_future_partitions(engine: AsyncEngine, months_forward: int = 3) -> None:
    """Roll partitions forward — called periodically by the maintenance worker."""
    async with engine.begin() as conn:
        for stmt in ddl.rolling_partitions_sql(months_back=0, months_forward=months_forward):
            await conn.execute(text(stmt))
