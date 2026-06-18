"""SSRF defence (Arch §14, PRD §9.4).

Users submit arbitrary crawl URLs, so every fetch — and every redirect hop — is
validated: scheme must be http/https, and the host's resolved IPs must not fall in
private/reserved/link-local ranges or hit a cloud metadata endpoint. This is the
application-layer half of the defence; a network-layer egress allowlist (the SSRF
proxy) is the second half.
"""

from __future__ import annotations

import asyncio
import ipaddress
import socket
from urllib.parse import urlsplit

# Extra explicit blocks on top of the stdlib ``is_private``/``is_reserved`` flags.
_EXTRA_BLOCKED_V4 = [
    ipaddress.ip_network("0.0.0.0/8"),
    ipaddress.ip_network("100.64.0.0/10"),   # CGNAT
    ipaddress.ip_network("169.254.0.0/16"),  # link-local incl. 169.254.169.254 metadata
    ipaddress.ip_network("192.0.0.0/24"),
    ipaddress.ip_network("192.0.2.0/24"),
    ipaddress.ip_network("198.18.0.0/15"),
    ipaddress.ip_network("198.51.100.0/24"),
    ipaddress.ip_network("203.0.113.0/24"),
]
_EXTRA_BLOCKED_V6 = [
    ipaddress.ip_network("::/128"),
    ipaddress.ip_network("::1/128"),
    ipaddress.ip_network("fc00::/7"),         # unique-local
    ipaddress.ip_network("fe80::/10"),        # link-local
    ipaddress.ip_network("fec0::/10"),
    ipaddress.ip_network("ff00::/8"),         # multicast
    ipaddress.ip_network("64:ff9b::/96"),     # NAT64 (can map to private v4)
]


class SsrfBlockedError(Exception):
    """Raised when a URL/host resolves to a forbidden address."""


def ip_is_blocked(ip_str: str) -> bool:
    try:
        ip = ipaddress.ip_address(ip_str)
    except ValueError:
        return True  # unparseable → block
    if (
        ip.is_private
        or ip.is_loopback
        or ip.is_link_local
        or ip.is_multicast
        or ip.is_reserved
        or ip.is_unspecified
    ):
        return True
    # IPv4-mapped IPv6 (::ffff:10.0.0.1) — unwrap and re-check.
    if isinstance(ip, ipaddress.IPv6Address) and ip.ipv4_mapped is not None:
        return ip_is_blocked(str(ip.ipv4_mapped))
    nets = _EXTRA_BLOCKED_V6 if ip.version == 6 else _EXTRA_BLOCKED_V4
    return any(ip in net for net in nets)


async def resolve_host(host: str) -> list[str]:
    """Resolve ``host`` to a de-duplicated list of IP strings (async, off the loop)."""
    loop = asyncio.get_running_loop()
    try:
        infos = await loop.run_in_executor(
            None, lambda: socket.getaddrinfo(host, None, proto=socket.IPPROTO_TCP)
        )
    except socket.gaierror as exc:
        raise SsrfBlockedError(f"DNS resolution failed for {host!r}") from exc
    return list({info[4][0] for info in infos})


async def assert_url_allowed(url: str) -> list[str]:
    """Validate one URL. Returns its resolved IPs or raises ``SsrfBlockedError``."""
    parts = urlsplit(url)
    if parts.scheme.lower() not in ("http", "https"):
        raise SsrfBlockedError(f"Scheme {parts.scheme!r} not allowed")
    host = parts.hostname
    if not host:
        raise SsrfBlockedError("URL has no host")

    # A literal IP host skips DNS but is still range-checked.
    try:
        ipaddress.ip_address(host)
        ips = [host]
    except ValueError:
        ips = await resolve_host(host)

    if not ips:
        raise SsrfBlockedError(f"No addresses resolved for {host!r}")
    for ip in ips:
        if ip_is_blocked(ip):
            raise SsrfBlockedError(f"Host {host!r} resolves to blocked address {ip}")
    return ips
