"""Manual proxy smoke test — run on the server from the backend/ directory.

    cd /home/ls_user/htdocs/72.62.81.34.nip.io/backend
    source venv/bin/activate
    python scripts/test_proxy.py                       # uses a default blocked URL
    python scripts/test_proxy.py https://www.quora.com # or pass your own

It reads the same .env the app uses and prints three things:
  1) your proxy config (so you can see it's switched on),
  2) your egress IP direct vs. through IPRoyal (proves the proxy + creds work),
  3) a real engine crawl of a blocked URL with the status + which egress was used.
"""

from __future__ import annotations

import asyncio
import sys

import httpx

from app.core.config import settings
from app.crawler.engine import CrawlConfig, CrawlEngine
from app.crawler.types import CrawlRequest
from app.integrations import proxy

DEFAULT_URL = "https://www.quora.com/"


async def show_config() -> None:
    print("── 1. CONFIG ───────────────────────────────")
    print(f"PROXY_ENABLED      : {settings.PROXY_ENABLED}")
    print(f"PROXY_MODE         : {settings.PROXY_MODE}  (effective: {proxy.mode()})")
    print(f"proxy host:port    : {settings.IPROYAL_PROXY_HOST}:{settings.IPROYAL_PROXY_PORT}")
    print(f"proxy configured?  : {bool(proxy.proxy_url())}")
    print()


async def show_egress_ip() -> None:
    print("── 2. EGRESS IP (direct vs proxy) ──────────")
    url = "https://api.ipify.org?format=json"
    try:
        async with httpx.AsyncClient(timeout=20) as c:
            direct = (await c.get(url)).json().get("ip")
        print(f"direct IP          : {direct}")
    except Exception as exc:  # noqa: BLE001
        print(f"direct IP          : ERROR {exc!r}")

    purl = proxy.proxy_url()
    if not purl:
        print("proxy IP           : (proxy not configured — skipping)")
        print()
        return
    try:
        async with httpx.AsyncClient(
            proxy=purl, verify=settings.PROXY_VERIFY_TLS, http2=False, timeout=settings.PROXY_TIMEOUT
        ) as c:
            proxied = (await c.get(url)).json().get("ip")
        print(f"proxy IP           : {proxied}   <-- should differ from direct")
    except Exception as exc:  # noqa: BLE001
        print(f"proxy IP           : ERROR {exc!r}   <-- creds/host/port problem")
    print()


async def crawl_once(url: str) -> None:
    print("── 3. REAL ENGINE CRAWL ────────────────────")
    print(f"url                : {url}")
    cfg = CrawlConfig.from_settings()
    async with CrawlEngine(cfg) as engine:
        art = await engine.crawl(CrawlRequest(source_url=url, target_url=url))
    print(f"http_status        : {art.http_status}")
    print(f"egress used        : {art.egress}   <-- 'proxy' means it escalated")
    print(f"fetch_error        : {art.fetch_error.value}")
    print(f"final_url          : {art.final_url}")
    verdict = "LOADED OK" if (art.http_status and art.http_status < 400) else "still blocked/failed"
    print(f"result             : {verdict}")
    print()


async def main() -> None:
    url = sys.argv[1] if len(sys.argv) > 1 else DEFAULT_URL
    await show_config()
    await show_egress_ip()
    await crawl_once(url)


if __name__ == "__main__":
    asyncio.run(main())
