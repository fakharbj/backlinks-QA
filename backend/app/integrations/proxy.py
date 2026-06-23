"""Proxy egress provider abstraction (IPRoyal Web Unblocker by default).

Keeps proxy concerns out of the crawler: the engine asks this module for a proxy
URL and the active mode, and routes a fetch through it when a page is blocked.
Credentials are read from env only (``core.config``) — never hardcoded.

Provider-agnostic: today it builds an IPRoyal Web Unblocker URL, but a second
provider can be added here without touching the crawler.
"""

from __future__ import annotations

from urllib.parse import quote

from app.core.config import settings


def is_enabled() -> bool:
    """True when a proxy is configured and not switched off."""
    return bool(
        settings.PROXY_ENABLED
        and settings.PROXY_MODE != "off"
        and settings.IPROYAL_PROXY_HOST
        and settings.IPROYAL_PROXY_USERNAME
        and settings.IPROYAL_PROXY_PASSWORD
    )


def mode() -> str:
    """Effective mode: 'off' | 'escalate' | 'always' (forced 'off' if unconfigured)."""
    return settings.PROXY_MODE if is_enabled() else "off"


def proxy_url() -> str | None:
    """Full ``http://user:pass@host:port`` URL, or None when disabled.

    Username/password are URL-encoded so credentials containing special characters
    don't break the URL.
    """
    if not is_enabled():
        return None
    user = quote(settings.IPROYAL_PROXY_USERNAME or "", safe="")
    pw = quote(settings.IPROYAL_PROXY_PASSWORD or "", safe="")
    return f"http://{user}:{pw}@{settings.IPROYAL_PROXY_HOST}:{settings.IPROYAL_PROXY_PORT}"
