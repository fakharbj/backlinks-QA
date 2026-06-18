"""Pytest fixtures.

The pure unit tests (normalization, robots, parsing, checks, scoring, security)
need no services. The integration API test needs Postgres + Redis; the ``live_stack``
fixture builds the schema on a throwaway engine and skips the test cleanly when the
services are unavailable, so ``pytest -q`` is always green locally.
"""

from __future__ import annotations

import asyncio

import pytest


@pytest.fixture(scope="session")
def live_stack():
    from sqlalchemy.ext.asyncio import create_async_engine

    from app.core.config import settings
    from app.db.init_db import init_models

    # Redis reachability (sync ping → simplest skip signal).
    try:
        import redis as redis_sync

        redis_sync.from_url(str(settings.REDIS_URL)).ping()
    except Exception as exc:  # noqa: BLE001
        pytest.skip(f"Redis unavailable: {exc}")

    async def _setup() -> None:
        engine = create_async_engine(
            str(settings.DATABASE_URL), connect_args={"statement_cache_size": 0}
        )
        try:
            await init_models(engine)
        finally:
            await engine.dispose()

    try:
        asyncio.run(_setup())
    except Exception as exc:  # noqa: BLE001
        pytest.skip(f"Postgres unavailable: {exc}")
    yield
