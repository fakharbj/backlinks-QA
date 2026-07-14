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
from app.integrations import proxy, serper_pool
from app.models.index_check import INDEXED, NOT_INDEXED, UNCERTAIN

log = get_logger("integrations.serp")

# Phrases Google shows for a zero-result query (locale-tolerant prefixes).
_ZERO_RESULT_MARKERS = (
    "did not match any documents",
    "did not match any articles",
    " - did not match",
    "no results found for",
)
# STRONG block/consent signals only. Weak words ("captcha"/"recaptcha"/"enablejs")
# appear in EVERY normal Google page's scripts, so matching them caused valid pages
# to be judged "blocked" — they are deliberately excluded.
_BLOCK_MARKERS = (
    "our systems have detected unusual traffic",
    "/sorry/index", "/sorry/?", "captcha-form",
    "before you continue to google", "consent.google.com",
    "to continue, please type the characters",
)
# Markers that a parseable results page was returned (basic gbv=1 HTML).
_RESULT_MARKERS = ("/url?q=", "result-stats", 'id="search"', 'id="rso"', 'class="g"')
_RESULT_COUNT_RE = re.compile(r"[Aa]bout ([\d,\.\s]+) results")
# Consent-bypass cookie so EU proxy exits don't hit the "before you continue" wall.
_CONSENT_COOKIE = "CONSENT=YES+cb.20210720-07-p0.en+FX+410; SOCS=CAISEwgDEgk0ODE3Nzk3MjQaAmVuIAEaBgiA_LyaBg"


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
    if any(marker in low for marker in _RESULT_MARKERS) or _RESULT_COUNT_RE.search(html):
        return INDEXED, parse_result_count(html), "results_present"
    return UNCERTAIN, None, "unrecognised_page"


async def check_indexed(source_page_url: str) -> dict:
    """Run a `site:` check for one source URL. Always returns a dict; never raises."""
    if settings.SERP_PROVIDER == "serper" and serper_pool.all_keys():
        return await _check_serper(source_page_url)
    if (
        settings.SERP_PROVIDER == "google_cse"
        and settings.GOOGLE_CSE_API_KEY
        and settings.GOOGLE_CSE_CX
    ):
        return await _check_google_cse(source_page_url)
    return await _check_proxy_scrape(source_page_url)


async def _check_serper(source_page_url: str) -> dict:
    """serper.dev Google Search API — reliable JSON; indexed if it returns results.

    Uses the key ROTATION POOL: the first key with credit answers; when a key is out
    of credit / invalid (401/402/403) it is retired and we transparently retry the
    same query with the next key, so a running batch never drops a check just because
    one key ran dry. Rate limits (429) and transient errors stay UNCERTAIN and keep
    the key. When every key is exhausted we return UNCERTAIN, never a false negative.
    """
    body = {"q": f"site:{source_page_url}", "num": 10}
    n = len(serper_pool.all_keys())
    attempts = 0
    async with httpx.AsyncClient(timeout=settings.INDEX_TIMEOUT_SECONDS) as client:
        while attempts < max(1, n):
            key = await serper_pool.active_key()
            if not key:
                return {"verdict": UNCERTAIN, "result_count": None,
                        "evidence": {"reason": "serper_all_keys_exhausted"}}
            attempts += 1
            try:
                resp = await client.post(
                    "https://google.serper.dev/search",
                    headers={"X-API-KEY": key, "Content-Type": "application/json"},
                    json=body,
                )
            except Exception as exc:  # noqa: BLE001 - transient network error; keep the key
                log.warning("serper_check_failed", url=source_page_url, error=repr(exc))
                return {"verdict": UNCERTAIN, "result_count": None,
                        "evidence": {"reason": "serper_error", "error": repr(exc)[:200]}}
            if resp.status_code in (401, 402, 403):
                # Bad key or out of credits → retire it and roll to the next key.
                from app.services import api_usage_service

                await api_usage_service.record(
                    "serper", ok=False, error=f"http_{resp.status_code}_key_retired"
                )
                await serper_pool.mark_dead(key)
                continue
            if resp.status_code == 429:
                # Rate limited (transient) — do NOT retire the key.
                from app.services import api_usage_service

                await api_usage_service.record("serper", ok=False, error="rate_limited")
                return {"verdict": UNCERTAIN, "result_count": None,
                        "evidence": {"reason": "serper_rate_limited"}}
            if resp.status_code != 200:
                return {"verdict": UNCERTAIN, "result_count": None,
                        "evidence": {"reason": f"serper_http_{resp.status_code}", "body": resp.text[:200]}}
            try:
                data = resp.json()
            except Exception as exc:  # noqa: BLE001
                return {"verdict": UNCERTAIN, "result_count": None,
                        "evidence": {"reason": "serper_bad_json", "error": repr(exc)[:200]}}
            await serper_pool.note_use(key, int(data.get("credits") or 1))
            from app.services import api_usage_service

            await api_usage_service.record("serper", ok=True)
            organic = data.get("organic") or []
            count = len(organic)
            verdict = INDEXED if count > 0 else NOT_INDEXED
            return {"verdict": verdict, "result_count": count,
                    "evidence": {"reason": "serper", "provider": "serper", "key_tail": key[-4:]}}
    return {"verdict": UNCERTAIN, "result_count": None,
            "evidence": {"reason": "serper_all_keys_exhausted"}}


async def _check_google_cse(source_page_url: str) -> dict:
    """Official Google Custom Search JSON API — reliable result counts."""
    params = {
        "key": settings.GOOGLE_CSE_API_KEY,
        "cx": settings.GOOGLE_CSE_CX,
        "q": f"site:{source_page_url}",
        "num": 1,
    }
    try:
        async with httpx.AsyncClient(timeout=settings.INDEX_TIMEOUT_SECONDS) as client:
            resp = await client.get("https://www.googleapis.com/customsearch/v1", params=params)
        if resp.status_code in (403, 429):  # quota / rate limit → don't guess
            return {"verdict": UNCERTAIN, "result_count": None,
                    "evidence": {"reason": f"cse_http_{resp.status_code}"}}
        if resp.status_code != 200:
            return {"verdict": UNCERTAIN, "result_count": None,
                    "evidence": {"reason": f"cse_http_{resp.status_code}", "body": resp.text[:200]}}
        data = resp.json()
        total = int(str(data.get("searchInformation", {}).get("totalResults", "0")) or "0")
    except Exception as exc:  # noqa: BLE001
        log.warning("cse_check_failed", url=source_page_url, error=repr(exc))
        return {"verdict": UNCERTAIN, "result_count": None,
                "evidence": {"reason": "cse_error", "error": repr(exc)[:200]}}
    verdict = INDEXED if total > 0 else NOT_INDEXED
    return {"verdict": verdict, "result_count": total,
            "evidence": {"reason": "cse", "provider": "google_cse"}}


async def _check_proxy_scrape(source_page_url: str) -> dict:
    query = f"site:{source_page_url}"
    # gbv=1 → Google's basic no-JavaScript HTML SERP, which is parseable server-side
    # (the modern SERP renders results via JS and is not).
    url = (
        f"{settings.INDEX_GOOGLE_ENDPOINT}?q={quote_plus(query)}"
        "&num=10&hl=en&gl=us&pws=0&gbv=1"
    )
    proxy_url = proxy.proxy_url()
    headers = {
        "User-Agent": settings.CRAWL_USER_AGENT,
        "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
        "Accept-Language": "en-US,en;q=0.9",
        "Cookie": _CONSENT_COOKIE,
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
