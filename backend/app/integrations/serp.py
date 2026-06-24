"""Google index check (`site:<url>`) via the IPRoyal proxy.

Determines whether the EXACT source URL is indexed by Google. The HTML parsing is
split into pure functions (``classify_serp_html`` / ``parse_result_count``) so the
verdict logic is unit-testable without the network. Any ambiguity (block, CAPTCHA,
consent wall, non-200, parse failure) returns UNCERTAIN — never a false
"not indexed".
"""

from __future__ import annotations

import re
from urllib.parse import quote_plus

import httpx

from app.core.config import settings
from app.core.logging import get_logger
from app.integrations import proxy
from app.models.index_check import INDEXED, NOT_INDEXED, UNCERTAIN

log = get_logger("integrations.serp")

# Phrases Google shows for a zero-result query (locale-tolerant prefixes).
_ZERO_RESULT_MARKERS = (
    "did not match any documents",
    "did not match any articles",
    " - did not match",
    "no results found for",
)
# Markers that mean "we were blocked / asked to verify" → uncertain, not negative.
_BLOCK_MARKERS = (
    "unusual traffic", "/sorry/", "recaptcha", "g-recaptcha", "captcha",
    "before you continue", "consent.google", "enablejs", "our systems have detected",
    "why did this happen",
)
_RESULT_COUNT_RE = re.compile(r"[Aa]bout ([\d,\.\s]+) results")


def parse_result_count(html: str) -> int | None:
    """Best-effort 'About X results' → int (None if not present)."""
    m = _RESULT_COUNT_RE.search(html)
    if not m:
        return None
    digits = re.sub(r"[^\d]", "", m.group(1))
    return int(digits) if digits else None


def classify_serp_html(status_code: int, html: str) -> tuple[str, int | None, str]:
    """Return (verdict, result_count, reason) for a Google results page."""
    if status_code != 200:
        return UNCERTAIN, None, f"http_{status_code}"
    if not html or len(html) < 200:
        return UNCERTAIN, None, "empty_body"
    low = html.lower()
    if any(marker in low for marker in _BLOCK_MARKERS):
        return UNCERTAIN, None, "blocked_or_consent"
    if any(marker in low for marker in _ZERO_RESULT_MARKERS):
        return NOT_INDEXED, 0, "zero_results_phrase"
    # A normal results page for a site: query → the URL is indexed.
    if 'id="search"' in low or "result-stats" in low or "/url?q=" in low or "<h3" in low:
        return INDEXED, parse_result_count(html), "results_present"
    return UNCERTAIN, None, "unrecognised_page"


async def check_indexed(source_page_url: str) -> dict:
    """Run a `site:` check for one source URL. Always returns a dict; never raises."""
    query = f"site:{source_page_url}"
    url = f"{settings.INDEX_GOOGLE_ENDPOINT}?q={quote_plus(query)}&num=10&hl=en&gl=us&pws=0"
    proxy_url = proxy.proxy_url()
    headers = {
        "User-Agent": settings.CRAWL_USER_AGENT,
        "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
        "Accept-Language": "en-US,en;q=0.9",
    }
    try:
        async with httpx.AsyncClient(
            proxy=proxy_url,
            verify=False if proxy_url else True,
            http2=False,
            timeout=settings.INDEX_TIMEOUT_SECONDS,
            follow_redirects=True,
        ) as client:
            resp = await client.get(url, headers=headers)
        verdict, count, reason = classify_serp_html(resp.status_code, resp.text)
    except Exception as exc:  # noqa: BLE001 - any failure is UNCERTAIN, never negative
        log.warning("serp_check_failed", url=source_page_url, error=repr(exc))
        return {"verdict": UNCERTAIN, "result_count": None,
                "evidence": {"reason": "request_error", "error": repr(exc)[:300]}}

    if verdict == UNCERTAIN:
        log.info("serp_uncertain", url=source_page_url, reason=reason, egress="proxy" if proxy_url else "direct")
    return {
        "verdict": verdict,
        "result_count": count,
        "evidence": {"reason": reason, "via_proxy": bool(proxy_url), "query": query},
    }
