"""Headless render escalation (Playwright/Chromium).

Only invoked when the link is absent in raw HTML *and* the page looks JS-driven
(cost control, PRD §8.5). Chromium is launched once per worker process and reused;
each render gets a fresh, isolated browser context. Sub-resource requests to
blocked (internal) hosts are aborted at the network layer as defence-in-depth.

Import-guarded: a process without Playwright installed can still import this module
(``RENDER_AVAILABLE is False``) — only the render pool needs the browser binary.
"""

from __future__ import annotations

import asyncio
import ipaddress
from dataclasses import dataclass
from urllib.parse import urlsplit

from app.crawler.ssrf import ip_is_blocked

try:  # pragma: no cover - availability depends on the image
    from playwright.async_api import async_playwright

    RENDER_AVAILABLE = True
except ImportError:  # pragma: no cover
    RENDER_AVAILABLE = False


@dataclass(slots=True)
class RenderOutcome:
    ok: bool
    html: str = ""
    final_url: str | None = None
    status: int | None = None
    error: str | None = None


def _host_is_obviously_internal(url: str) -> bool:
    host = urlsplit(url).hostname or ""
    try:
        return ip_is_blocked(host)  # literal-IP hosts only; DNS handled by egress proxy
    except ValueError:
        return False


class BrowserManager:
    """Lazily-launched, process-wide Chromium with a bounded render semaphore."""

    def __init__(self, *, user_agent: str, max_contexts: int = 6) -> None:
        self._user_agent = user_agent
        self._sem = asyncio.Semaphore(max_contexts)
        self._pw = None
        self._browser = None
        self._lock = asyncio.Lock()

    async def _ensure_browser(self):
        if self._browser is not None:
            return self._browser
        async with self._lock:
            if self._browser is None:
                self._pw = await async_playwright().start()
                self._browser = await self._pw.chromium.launch(
                    headless=True,
                    args=[
                        "--no-sandbox",
                        "--disable-dev-shm-usage",
                        "--disable-gpu",
                        "--disable-background-networking",
                    ],
                )
        return self._browser

    async def render(
        self, url: str, *, timeout_ms: int, wait_until: str = "networkidle"
    ) -> RenderOutcome:
        if not RENDER_AVAILABLE:
            return RenderOutcome(ok=False, error="playwright_unavailable")

        async with self._sem:
            try:
                browser = await self._ensure_browser()
            except Exception as exc:  # noqa: BLE001
                return RenderOutcome(ok=False, error=f"launch_failed: {exc!r}")

            context = await browser.new_context(
                user_agent=self._user_agent,
                ignore_https_errors=False,
                java_script_enabled=True,
                bypass_csp=False,
            )
            try:
                await context.route("**/*", _guard_route)
                page = await context.new_page()
                response = await page.goto(url, timeout=timeout_ms, wait_until=wait_until)
                # Allow late hydration of client-rendered links.
                await page.wait_for_timeout(min(1500, timeout_ms // 4))
                html = await page.content()
                return RenderOutcome(
                    ok=True,
                    html=html,
                    final_url=page.url,
                    status=response.status if response else None,
                )
            except Exception as exc:  # noqa: BLE001
                return RenderOutcome(ok=False, error=repr(exc))
            finally:
                await context.close()

    async def close(self) -> None:
        if self._browser is not None:
            await self._browser.close()
        if self._pw is not None:
            await self._pw.stop()
        self._browser = self._pw = None


async def _guard_route(route) -> None:  # pragma: no cover - network side-effect
    request_url = route.request.url
    if _host_is_obviously_internal(request_url):
        await route.abort()
        return
    await route.continue_()
