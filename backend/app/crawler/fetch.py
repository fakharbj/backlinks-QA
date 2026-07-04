"""Raw HTTP fetch with manual redirect following (httpx).

Redirects are followed by hand so that every hop is (a) recorded for the RDR-*
checks and (b) re-validated by the SSRF guard — auto-redirect would let a public
URL bounce to ``169.254.169.254``. Bodies are streamed and aborted past the size
cap to defend against decompression bombs.
"""

from __future__ import annotations

import re
import ssl
import time
import zlib
from dataclasses import dataclass, field
from urllib.parse import urljoin

import httpx

from app.crawler.ssrf import SsrfBlockedError, assert_url_allowed
from app.crawler.types import CrawlRequest, FetchError, RedirectHop

_REDIRECT_STATUSES = {301, 302, 303, 307, 308}

# JS/meta-refresh redirect stubs (parked/expired domains, "lander" shells).
# Only tiny bodies with NO real content qualify — a normal article that happens
# to use window.location somewhere in a script must never match.
_STUB_MAX_BYTES = 2048
_JS_REDIRECT_RE = re.compile(
    r"""(?:window\.|document\.|top\.)?location(?:\.href)?\s*=\s*["']([^"']+)["']""",
    re.IGNORECASE,
)
_META_REFRESH_RE = re.compile(
    r"""<meta[^>]+http-equiv\s*=\s*["']?refresh["']?[^>]*content\s*=\s*["'][^"']*url\s*=\s*([^"'>\s]+)""",
    re.IGNORECASE,
)


def _stub_redirect_target(body_bytes: bytes, base_url: str) -> str | None:
    """If the page is nothing but a JS/meta redirect shell, return where it
    points (absolute); otherwise None."""
    if len(body_bytes) > _STUB_MAX_BYTES:
        return None
    try:
        text = body_bytes.decode("utf-8", errors="replace")
    except Exception:  # noqa: BLE001
        return None
    if "<a " in text.lower():  # real links present → real page, not a stub
        return None
    m = _META_REFRESH_RE.search(text) or _JS_REDIRECT_RE.search(text)
    if not m:
        return None
    target = m.group(1).strip()
    if not target or target.startswith(("javascript:", "#")):
        return None
    resolved = urljoin(base_url, target)
    return resolved if resolved.startswith(("http://", "https://")) else None


@dataclass(slots=True)
class FetchOutcome:
    error: FetchError = FetchError.NONE
    error_detail: str | None = None
    status: int | None = None
    final_url: str | None = None
    headers: dict[str, str] = field(default_factory=dict)
    raw_header_pairs: list[tuple[str, str]] = field(default_factory=list)
    body: str = ""
    body_bytes: int = 0
    content_type: str | None = None
    encoding: str | None = None
    redirect_chain: list[RedirectHop] = field(default_factory=list)
    tls_valid: bool | None = None
    duration_ms: int | None = None


def build_client(
    *,
    user_agent: str,
    connect_timeout: float,
    read_timeout: float,
    total_timeout: float,
    proxy: str | None = None,
    verify: bool = True,
    http2: bool = True,
) -> httpx.AsyncClient:
    timeout = httpx.Timeout(total_timeout, connect=connect_timeout, read=read_timeout)
    limits = httpx.Limits(max_connections=200, max_keepalive_connections=40)
    return httpx.AsyncClient(
        follow_redirects=False,            # we follow manually (see module docstring)
        timeout=timeout,
        limits=limits,
        http2=http2,
        verify=verify,
        proxy=proxy,
        headers={
            # A full, browser-like header set. Bare bot-style requests (just a
            # User-Agent + Accept) are a common trigger for 403/WAF blocks; real
            # browsers always send the Sec-Fetch and client-hint headers below.
            "User-Agent": user_agent,
            "Accept": (
                "text/html,application/xhtml+xml,application/xml;q=0.9,"
                "image/avif,image/webp,*/*;q=0.8"
            ),
            "Accept-Language": "en-US,en;q=0.9",
            "Accept-Encoding": "gzip, deflate, br",
            "Upgrade-Insecure-Requests": "1",
            "Sec-Fetch-Dest": "document",
            "Sec-Fetch-Mode": "navigate",
            "Sec-Fetch-Site": "none",
            "Sec-Fetch-User": "?1",
            "Sec-CH-UA": '"Chromium";v="124", "Not.A/Brand";v="24", "Google Chrome";v="124"',
            "Sec-CH-UA-Mobile": "?0",
            "Sec-CH-UA-Platform": '"Windows"',
        },
    )


# Statuses that usually mean "blocked / try again as a different agent" rather
# than a genuine dead page — we retry these once with the fallback User-Agent.
_BLOCK_RETRY_STATUSES = {403, 429, 503}


def _classify_exc(exc: Exception) -> tuple[FetchError, str]:
    if isinstance(exc, SsrfBlockedError):
        return FetchError.BLOCKED_SSRF, str(exc)
    if isinstance(exc, (httpx.ConnectTimeout, httpx.ReadTimeout, httpx.PoolTimeout)):
        return FetchError.TIMEOUT, repr(exc)
    if isinstance(exc, (ssl.SSLError, httpx.ConnectError)) and _looks_tls(exc):
        return FetchError.SSL, repr(exc)
    if isinstance(exc, httpx.ConnectError):
        # DNS failures surface as ConnectError with a getaddrinfo cause.
        if "getaddrinfo" in repr(exc) or "Name or service not known" in repr(exc):
            return FetchError.DNS, repr(exc)
        return FetchError.CONNECTION, repr(exc)
    if isinstance(exc, (httpx.RemoteProtocolError, httpx.ReadError, httpx.WriteError)):
        return FetchError.CONNECTION, repr(exc)
    if isinstance(exc, httpx.TooManyRedirects):
        return FetchError.TOO_MANY_REDIRECTS, repr(exc)
    return FetchError.UNKNOWN, repr(exc)


def _looks_tls(exc: Exception) -> bool:
    text = repr(exc).lower()
    return any(k in text for k in ("ssl", "certificate", "tls", "handshake"))


async def _read_capped(response: httpx.Response, cap: int) -> tuple[bytes, bool]:
    chunks: list[bytes] = []
    total = 0
    async for chunk in response.aiter_bytes():
        total += len(chunk)
        if total > cap:
            return b"".join(chunks), True
        chunks.append(chunk)
    return b"".join(chunks), False


# Hard ceiling on bytes produced by the defensive decompressor below — guards
# against a decompression bomb (a small compressed body inflating to GBs).
_DECOMP_OUTPUT_CAP = 32 * 1024 * 1024  # 32 MiB


def _bounded_inflate(data: bytes, wbits: int) -> bytes:
    """zlib/gzip inflate capped at ``_DECOMP_OUTPUT_CAP`` (truncated, not unbounded)."""
    return zlib.decompressobj(wbits).decompress(data, _DECOMP_OUTPUT_CAP)


def _maybe_decompress(data: bytes) -> bytes:
    """Defensive net against a missing/failed Content-Encoding decoder.

    httpx normally decompresses the body itself, so this is a no-op on a correctly
    decoded page. But if a decoder package is unavailable (e.g. ``brotli`` not
    installed) httpx silently passes the *compressed* bytes through — the HTML
    parser then finds 0 links and we emit a false "link missing". If the body
    still bears a recognizable compression magic, decompress it here so the parser
    always sees real HTML. Brotli has no fixed magic, so it must be handled by the
    installed library (pinned in requirements.txt); gzip/zlib/zstd are caught here.
    """
    if len(data) < 4:
        return data
    head = data[:4]
    try:
        if head[:2] == b"\x1f\x8b":  # gzip
            return _bounded_inflate(data, 31)  # zlib.MAX_WBITS | 16
        if head == b"\x28\xb5\x2f\xfd":  # zstandard
            import zstandard

            return zstandard.ZstdDecompressor().decompress(
                data, max_output_size=_DECOMP_OUTPUT_CAP
            )
        if head[0] == 0x78 and head[1] in (0x01, 0x5E, 0x9C, 0xDA):  # zlib/deflate
            return _bounded_inflate(data, 15)
    except Exception:  # noqa: BLE001 — corrupt/partial body: leave as-is for decode
        return data
    return data


async def fetch_raw(
    client: httpx.AsyncClient,
    url: str,
    request: CrawlRequest,
    *,
    max_redirects: int,
    max_bytes: int,
    retry_user_agent: str | None = None,
) -> FetchOutcome:
    """Fetch ``url``, following redirects manually with SSRF re-checks per hop.

    If a page returns a block status (403/429/503) and ``retry_user_agent`` is
    given, the page is fetched once more with that agent before giving up — many
    sites that block our default agent allow a well-known crawler like Googlebot.
    """
    outcome = FetchOutcome()
    started = time.perf_counter()
    current = url
    seen: set[str] = set()
    retried_block = False

    try:
        for hop in range(max_redirects + 1):
            try:
                await assert_url_allowed(current)
            except SsrfBlockedError as exc:
                outcome.error, outcome.error_detail = FetchError.BLOCKED_SSRF, str(exc)
                outcome.final_url = current
                return outcome

            if current in seen:
                outcome.error = FetchError.REDIRECT_LOOP
                outcome.error_detail = f"loop at {current}"
                outcome.final_url = current
                return outcome
            seen.add(current)

            req = client.build_request("GET", current)
            response = await client.send(req, stream=True)
            outcome.tls_valid = current.startswith("https://")

            # Blocked? Retry this exact URL once with the fallback agent.
            if (
                retry_user_agent
                and not retried_block
                and response.status_code in _BLOCK_RETRY_STATUSES
            ):
                retried_block = True
                await response.aclose()
                req = client.build_request(
                    "GET", current, headers={"User-Agent": retry_user_agent}
                )
                response = await client.send(req, stream=True)

            if response.status_code in _REDIRECT_STATUSES and response.headers.get("location"):
                location = str(response.url.join(response.headers["location"]))
                outcome.redirect_chain.append(
                    RedirectHop(url=current, status=response.status_code, location=location)
                )
                await response.aclose()
                if hop >= max_redirects:
                    outcome.error = FetchError.TOO_MANY_REDIRECTS
                    outcome.final_url = location
                    return outcome
                current = location
                continue

            # Terminal response — read (capped) and finish.
            body_bytes, too_large = await _read_capped(response, max_bytes)
            await response.aclose()
            body_bytes = _maybe_decompress(body_bytes)

            # Stub pages: some hosts (notably parked/expired domains) answer 200
            # with a tiny HTML shell whose ONLY content is a JS or meta-refresh
            # redirect. Browsers follow it; a naive crawler would report a
            # healthy "200, no redirects" for a page that is effectively gone.
            # Treat it as a redirect hop so the chain and final URL stay honest.
            stub_target = _stub_redirect_target(body_bytes, str(response.url))
            if stub_target and hop < max_redirects:
                outcome.redirect_chain.append(
                    RedirectHop(
                        url=current, status=response.status_code, location=stub_target
                    )
                )
                current = stub_target
                continue

            outcome.redirect_chain.append(
                RedirectHop(url=current, status=response.status_code)
            )
            outcome.status = response.status_code
            outcome.final_url = str(response.url)
            outcome.headers = {k.lower(): v for k, v in response.headers.items()}
            outcome.raw_header_pairs = list(response.headers.multi_items())
            outcome.content_type = response.headers.get("content-type")
            outcome.encoding = response.encoding or response.charset_encoding
            outcome.body_bytes = len(body_bytes)
            if too_large:
                outcome.error = FetchError.TOO_LARGE
                outcome.error_detail = f"exceeded {max_bytes} bytes"
            try:
                outcome.body = body_bytes.decode(outcome.encoding or "utf-8", errors="replace")
            except (LookupError, ValueError):
                outcome.body = body_bytes.decode("utf-8", errors="replace")
            return outcome

    except Exception as exc:  # noqa: BLE001 — classified, never swallowed silently
        outcome.error, outcome.error_detail = _classify_exc(exc)
        outcome.final_url = current
        return outcome
    finally:
        outcome.duration_ms = int((time.perf_counter() - started) * 1000)

    return outcome
