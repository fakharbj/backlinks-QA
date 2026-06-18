"""Raw HTTP fetch with manual redirect following (httpx).

Redirects are followed by hand so that every hop is (a) recorded for the RDR-*
checks and (b) re-validated by the SSRF guard — auto-redirect would let a public
URL bounce to ``169.254.169.254``. Bodies are streamed and aborted past the size
cap to defend against decompression bombs.
"""

from __future__ import annotations

import ssl
import time
from dataclasses import dataclass, field

import httpx

from app.crawler.ssrf import SsrfBlockedError, assert_url_allowed
from app.crawler.types import CrawlRequest, FetchError, RedirectHop

_REDIRECT_STATUSES = {301, 302, 303, 307, 308}


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
) -> httpx.AsyncClient:
    timeout = httpx.Timeout(total_timeout, connect=connect_timeout, read=read_timeout)
    limits = httpx.Limits(max_connections=200, max_keepalive_connections=40)
    return httpx.AsyncClient(
        follow_redirects=False,            # we follow manually (see module docstring)
        timeout=timeout,
        limits=limits,
        http2=True,
        verify=verify,
        proxy=proxy,
        headers={
            "User-Agent": user_agent,
            "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
            "Accept-Language": "en-US,en;q=0.9",
            "Accept-Encoding": "gzip, deflate, br",
        },
    )


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


async def fetch_raw(
    client: httpx.AsyncClient,
    url: str,
    request: CrawlRequest,
    *,
    max_redirects: int,
    max_bytes: int,
) -> FetchOutcome:
    """Fetch ``url``, following redirects manually with SSRF re-checks per hop."""
    outcome = FetchOutcome()
    started = time.perf_counter()
    current = url
    seen: set[str] = set()

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
