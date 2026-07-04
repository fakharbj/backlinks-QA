"""Per-process worker runtime helpers.

A single long-lived event loop is reused for every task in a worker process so the
cached async Redis/SQLAlchemy clients stay bound to one loop (creating a fresh loop
per task would orphan them). Also provides the crawler's injected dependencies:
a Redis robots cache, a per-domain token-bucket rate limiter, and a lazy browser.
"""

from __future__ import annotations

import asyncio
from typing import Awaitable, TypeVar

from app.core.config import settings
from app.core.redis import (
    allow_domain_request,
    get_redis,
    is_domain_circuit_open,
)

T = TypeVar("T")

_loop: asyncio.AbstractEventLoop | None = None
_browser = None


def run_async(coro: Awaitable[T]) -> T:
    """Run ``coro`` to completion on this process's persistent event loop."""
    global _loop
    if _loop is None or _loop.is_closed():
        _loop = asyncio.new_event_loop()
        asyncio.set_event_loop(_loop)
    return _loop.run_until_complete(coro)


class RedisRobotsCache:
    """Implements ``app.crawler.engine.RobotsCache`` over Redis."""

    async def get(self, key: str) -> str | None:
        return await get_redis().get(key)

    async def set(self, key: str, value: str, ttl: int) -> None:
        await get_redis().set(key, value, ex=ttl)


def make_rate_limiter(rate: float, capacity: int):
    """Return an async callable enforcing the per-domain token bucket (fail-open).

    Waits up to a bounded time for a token, then proceeds — the domain sharding and
    per-domain concurrency cap still bound pressure, so we never silently drop a link.
    """
    max_wait = max(2.0, capacity / max(rate, 0.1)) + 2.0

    async def limiter(domain: str) -> None:
        if await is_domain_circuit_open(domain):
            # Breaker open: brief courtesy wait, then let the fetch proceed (it will
            # likely fail and re-trip the breaker, which is the intended back-off).
            await asyncio.sleep(0.25)
            return
        waited = 0.0
        while waited < max_wait:
            if await allow_domain_request(domain, rate=rate, capacity=capacity):
                return
            await asyncio.sleep(0.2)
            waited += 0.2

    return limiter


def get_browser():
    """Lazy, process-wide Playwright browser (render pool only)."""
    global _browser
    if _browser is None:
        from app.crawler.render import RENDER_AVAILABLE, BrowserManager

        if not RENDER_AVAILABLE:
            return None
        # NOTE: chromium rejects authenticated proxies (ERR_PROXY_AUTH_UNSUPPORTED),
        # so renders go direct; pages whose content stays bot-walled classify as
        # "Needs review — JavaScript page" instead of a false "link missing".
        _browser = BrowserManager(user_agent=settings.CRAWL_USER_AGENT, max_contexts=6)
    return _browser
