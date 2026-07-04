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
    """Abort sub-requests to literal internal IPs (169.254.…, 10.…, ::1 …).

    Domain names pass — ``ip_is_blocked`` treats anything unparseable as
    "block", which is right for the fetch path but here silently aborted EVERY
    request to a normal hostname and broke rendering for all real websites.
    """
    host = urlsplit(url).hostname or ""
    if not host:
        return True
    try:
        ipaddress.ip_address(host)
    except ValueError:
        return False  # a domain name, not a literal IP → allowed
    return ip_is_blocked(host)


class BrowserManager:
    """Lazily-launched, process-wide Chromium with a bounded render semaphore.

    ``proxy_url`` (http://user:pass@host:port) routes ALL browser traffic
    through the unblocker — pages worth rendering are usually the ones whose
    in-page API calls get bot-walled from a datacenter IP (e.g. notion.site).
    The unblocker MITMs TLS, so certificate errors are ignored when proxied.
    """

    def __init__(
        self, *, user_agent: str, max_contexts: int = 6, proxy_url: str | None = None
    ) -> None:
        self._user_agent = user_agent
        self._sem = asyncio.Semaphore(max_contexts)
        self._pw = None
        self._browser = None
        self._lock = asyncio.Lock()
        self._proxy = self._parse_proxy(proxy_url) if proxy_url else None

    @staticmethod
    def _parse_proxy(url: str) -> dict:
        from urllib.parse import unquote, urlsplit

        parts = urlsplit(url)
        proxy: dict = {"server": f"{parts.scheme}://{parts.hostname}:{parts.port}"}
        if parts.username:
            proxy["username"] = unquote(parts.username)
        if parts.password:
            proxy["password"] = unquote(parts.password)
        return proxy

    async def _ensure_browser(self):
        if self._browser is not None:
            return self._browser
        async with self._lock:
            if self._browser is None:
                self._pw = await async_playwright().start()
                self._browser = await self._pw.chromium.launch(
                    headless=True,
                    proxy=self._proxy,
                    args=[
                        "--no-sandbox",
                        "--disable-dev-shm-usage",
                        "--disable-gpu",
                        "--disable-background-networking",
                    ],
                )
        return self._browser

    async def render(
        self,
        url: str,
        *,
        timeout_ms: int,
        wait_until: str = "networkidle",
        wait_selector: str | None = None,
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
                # The unblocker proxy MITMs TLS — its certs never validate.
                ignore_https_errors=self._proxy is not None,
                java_script_enabled=True,
                bypass_csp=False,
            )
            try:
                await context.route("**/*", _guard_route)
                page = await context.new_page()
                # "networkidle" never settles on apps with live connections
                # (Notion, chat widgets) and can fail navigation outright —
                # always land on domcontentloaded, then wait for what QA
                # actually needs: the target link itself (or a bounded
                # hydration pause when no selector is given).
                response = await page.goto(
                    url, timeout=timeout_ms, wait_until="domcontentloaded"
                )
                if wait_selector:
                    try:
                        await page.wait_for_selector(
                            wait_selector, timeout=max(2000, timeout_ms // 2), state="attached"
                        )
                    except Exception:  # noqa: BLE001 — selector may never appear
                        pass
                else:
                    await page.wait_for_timeout(min(4000, timeout_ms // 3))
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
