"""serper.dev key-rotation pool (unit — no network, no Redis).

Redis is forced unavailable so the pool exercises its in-process fallback; that
keeps the test hermetic while covering the ordering + drain-one-then-next logic.
"""

import asyncio

import pytest

from app.core.config import settings
from app.integrations import serper_pool


@pytest.fixture(autouse=True)
def _force_memory_and_clean(monkeypatch):
    def _boom(*a, **k):  # noqa: ANN002, ANN003
        raise RuntimeError("no redis in test")

    monkeypatch.setattr("app.core.redis.get_redis", _boom, raising=False)
    serper_pool._mem_dead.clear()
    yield
    serper_pool._mem_dead.clear()


def test_all_keys_parses_pool_dedups_and_appends_legacy(monkeypatch):
    monkeypatch.setattr(settings, "SERPER_API_KEYS", " k1, k2 ,k3,, k2 ", raising=False)
    monkeypatch.setattr(settings, "SERPER_API_KEY", "legacy", raising=False)
    # order preserved, blanks + duplicates dropped, legacy single key appended last
    assert serper_pool.all_keys() == ["k1", "k2", "k3", "legacy"]


def test_all_keys_empty(monkeypatch):
    monkeypatch.setattr(settings, "SERPER_API_KEYS", "", raising=False)
    monkeypatch.setattr(settings, "SERPER_API_KEY", None, raising=False)
    assert serper_pool.all_keys() == []


def test_rotation_drains_one_then_next(monkeypatch):
    monkeypatch.setattr(settings, "SERPER_API_KEYS", "k1,k2,k3", raising=False)
    monkeypatch.setattr(settings, "SERPER_API_KEY", None, raising=False)

    async def scenario():
        assert await serper_pool.active_key() == "k1"   # use the first key
        await serper_pool.mark_dead("k1")
        assert await serper_pool.active_key() == "k2"   # roll to the next
        await serper_pool.mark_dead("k2")
        await serper_pool.mark_dead("k3")
        assert await serper_pool.active_key() is None    # all exhausted → caller returns UNCERTAIN

    asyncio.run(scenario())


def test_status_marks_active_and_exhausted(monkeypatch):
    monkeypatch.setattr(settings, "SERPER_API_KEYS", "k1,k2", raising=False)
    monkeypatch.setattr(settings, "SERPER_API_KEY", None, raising=False)

    async def scenario():
        await serper_pool.mark_dead("k1")
        st = await serper_pool.status()
        assert st["configured"] == 2
        assert st["exhausted"] == 1
        assert st["active_index"] == 1
        assert {it["index"]: it["state"] for it in st["keys"]} == {0: "exhausted", 1: "active"}

    asyncio.run(scenario())
