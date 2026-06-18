"""Async engines and session factories (primary + read replica).

Writes use ``get_session`` (primary). Read-only endpoints use ``get_read_session``
(replica DSN if configured, else primary). When fronted by PgBouncer in
transaction-pooling mode we disable prepared-statement caching, which is otherwise
incompatible with that mode.
"""

from __future__ import annotations

from collections.abc import AsyncIterator
from contextlib import asynccontextmanager

from sqlalchemy.ext.asyncio import (
    AsyncEngine,
    AsyncSession,
    async_sessionmaker,
    create_async_engine,
)

from app.core.config import settings


def _connect_args() -> dict:
    if settings.DB_USE_PGBOUNCER:
        # asyncpg: disabling the statement cache makes us PgBouncer-safe.
        return {"statement_cache_size": 0, "prepared_statement_cache_size": 0}
    return {}


def _make_engine(url: str) -> AsyncEngine:
    return create_async_engine(
        url,
        echo=settings.DB_ECHO,
        pool_pre_ping=True,
        pool_size=settings.DB_POOL_SIZE,
        max_overflow=settings.DB_MAX_OVERFLOW,
        pool_timeout=settings.DB_POOL_TIMEOUT,
        pool_recycle=1800,
        connect_args=_connect_args(),
    )


engine: AsyncEngine = _make_engine(str(settings.DATABASE_URL))
read_engine: AsyncEngine = (
    _make_engine(settings.read_database_url)
    if settings.DATABASE_REPLICA_URL
    else engine
)

SessionLocal = async_sessionmaker(engine, expire_on_commit=False, autoflush=False)
ReadSessionLocal = async_sessionmaker(
    read_engine, expire_on_commit=False, autoflush=False
)


@asynccontextmanager
async def session_scope() -> AsyncIterator[AsyncSession]:
    """Transactional scope for workers/scripts: commit on success, rollback on error."""
    async with SessionLocal() as session:
        try:
            yield session
            await session.commit()
        except Exception:
            await session.rollback()
            raise


# ── FastAPI dependencies ────────────────────────────────────────────────────────
async def get_session() -> AsyncIterator[AsyncSession]:
    """Primary (read-write) session. Caller controls commit."""
    async with SessionLocal() as session:
        try:
            yield session
        except Exception:
            await session.rollback()
            raise


async def get_read_session() -> AsyncIterator[AsyncSession]:
    """Replica (read-only) session for dashboards/grids/detail reads."""
    async with ReadSessionLocal() as session:
        yield session


async def dispose_engines() -> None:
    await engine.dispose()
    if read_engine is not engine:
        await read_engine.dispose()
