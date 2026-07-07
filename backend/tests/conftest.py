"""Pytest fixtures.

The pure unit tests (normalization, robots, parsing, checks, scoring, security)
need no services. The integration API test needs Postgres + Redis; the ``live_stack``
fixture builds the schema on a throwaway engine and skips the test cleanly when the
services are unavailable, so ``pytest -q`` is always green locally.
"""

from __future__ import annotations

import asyncio

import pytest


@pytest.fixture(autouse=True)
def _open_registration_for_tests():
    """Tests register their own throwaway accounts; keep signup open under test
    (prod default is closed — admins create accounts from the Team desk)."""
    from app.core.config import settings

    original = settings.ALLOW_PUBLIC_REGISTRATION
    settings.ALLOW_PUBLIC_REGISTRATION = True
    yield
    settings.ALLOW_PUBLIC_REGISTRATION = original


@pytest.fixture(scope="session")
def live_stack():
    import os

    from sqlalchemy.ext.asyncio import create_async_engine

    from app.core.config import settings
    from app.db.init_db import init_models

    # SAFETY GUARD — never write throwaway test accounts into a real database.
    # These integration tests register workspaces/users/projects via the API and
    # do NOT clean up, so running them against the production DB (name
    # ``linksentinel``) silently pollutes it. Only run when DATABASE_URL points at
    # an isolated ``*_test`` database, unless explicitly overridden.
    _dbname = str(settings.DATABASE_URL).rsplit("/", 1)[-1].split("?")[0]
    if not _dbname.endswith("_test") and os.getenv("LINKSENTINEL_TEST_ALLOW_NONTEST_DB") != "1":
        pytest.skip(
            f"refusing to run DB-writing integration tests against non-'_test' database "
            f"'{_dbname}' (point DATABASE_URL at a *_test DB, or set "
            f"LINKSENTINEL_TEST_ALLOW_NONTEST_DB=1 to override)"
        )

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
