"""Moz Links API — Domain Authority, Page Authority, and Spam Score.

These are Moz's proprietary metrics; they cannot be derived from crawling a page,
so we fetch them from the Moz Links API (https://lsapi.seomoz.com/v2/url_metrics)
and cache per source domain in Redis for ``MOZ_CACHE_DAYS`` (they move slowly).

The whole module is a no-op unless ``MOZ_ENABLED`` is set and a token is present,
so a crawl never fails because metrics are unavailable. ``enrich`` writes the
result into ``BacklinkRecord.extra['moz']`` — the model's existing JSONB bag — so
no schema migration is needed.
"""

from __future__ import annotations

import json
from datetime import datetime, timezone
from typing import Any

import httpx

from app.core.config import settings
from app.core.logging import get_logger
from app.core.redis import get_redis

log = get_logger("integrations.moz")

_CACHE_PREFIX = "moz:metrics:"
_NEGATIVE = "__none__"  # cache misses too, so we don't hammer Moz for dead domains


def is_enabled() -> bool:
    if not settings.MOZ_ENABLED:
        return False
    if settings.MOZ_PROVIDER == "rapidapi":
        return bool(settings.RAPIDAPI_KEY)
    return bool(
        settings.MOZ_API_TOKEN
        or (settings.MOZ_ACCESS_ID and settings.MOZ_SECRET_KEY)
    )


async def domain_metrics(domain: str) -> dict[str, Any] | None:
    """Return ``{da, pa, spam_score}`` for a registrable domain, or None.

    Cached in Redis (positive and negative) so a 100-link batch on the same
    domain makes at most one Moz call.
    """
    if not is_enabled() or not domain:
        return None

    redis = get_redis()
    cache_key = f"{_CACHE_PREFIX}{domain.lower()}"
    try:
        cached = await redis.get(cache_key)
    except Exception:  # noqa: BLE001 - cache is best-effort
        cached = None
    if cached == _NEGATIVE:
        return None
    if cached:
        try:
            return json.loads(cached)
        except ValueError:
            pass

    metrics = await _fetch_from_moz(domain)
    ttl = max(1, settings.MOZ_CACHE_DAYS) * 86400
    try:
        await redis.set(cache_key, json.dumps(metrics) if metrics else _NEGATIVE, ex=ttl)
    except Exception:  # noqa: BLE001
        pass
    return metrics


async def _fetch_from_moz(domain: str) -> dict[str, Any] | None:
    """Fetch DA/PA/Spam for one domain from the configured provider."""
    if settings.MOZ_PROVIDER == "rapidapi":
        endpoint = settings.RAPIDAPI_DA_ENDPOINT
        payload = {"q": domain}
        headers = {
            "Content-Type": "application/json",
            "x-rapidapi-host": settings.RAPIDAPI_HOST,
            "x-rapidapi-key": settings.RAPIDAPI_KEY or "",
        }
        auth = None
    else:
        endpoint = settings.MOZ_API_ENDPOINT
        payload = {"targets": [domain]}
        headers = {"Content-Type": "application/json"}
        auth = None
        if settings.MOZ_API_TOKEN:
            headers["Authorization"] = f"Bearer {settings.MOZ_API_TOKEN}"
        elif settings.MOZ_ACCESS_ID and settings.MOZ_SECRET_KEY:
            auth = (settings.MOZ_ACCESS_ID, settings.MOZ_SECRET_KEY)

    try:
        async with httpx.AsyncClient(timeout=settings.MOZ_TIMEOUT_SECONDS) as client:
            resp = await client.post(endpoint, json=payload, headers=headers, auth=auth)
        if resp.status_code != 200:
            log.warning("moz_http_error", domain=domain, status=resp.status_code,
                        body=resp.text[:300])
            return None
        data = resp.json()
    except Exception as exc:  # noqa: BLE001 - never let metrics break a crawl
        log.warning("moz_request_failed", domain=domain, error=repr(exc))
        return None

    return _parse_metrics(data)


# Possible key names for each metric across providers (Moz official + RapidAPI
# proxies vary), checked case-insensitively at any nesting depth.
_DA_KEYS = ("domain_authority", "da", "domainauthority", "domain_auth")
_PA_KEYS = ("page_authority", "pa", "pageauthority", "page_auth")
_SPAM_KEYS = ("spam_score", "spam", "spamscore", "spam_score_percent")


def _parse_metrics(data: Any) -> dict[str, Any] | None:
    """Pull DA/PA/Spam out of any provider's response shape."""
    flat: dict[str, Any] = {}
    _flatten(data, flat)
    da = _first(flat, _DA_KEYS)
    pa = _first(flat, _PA_KEYS)
    spam = _first(flat, _SPAM_KEYS)
    if da is None and pa is None and spam is None:
        return None
    return {"da": da, "pa": pa, "spam_score": spam}


def _flatten(data: Any, out: dict[str, Any]) -> None:
    """Collect every scalar leaf keyed by its (lowercased) field name."""
    if isinstance(data, dict):
        for key, value in data.items():
            if isinstance(value, (dict, list)):
                _flatten(value, out)
            elif key.lower() not in out:
                out[key.lower()] = value
    elif isinstance(data, list):
        for item in data:
            _flatten(item, out)


def _first(flat: dict[str, Any], keys: tuple[str, ...]) -> int | None:
    for key in keys:
        if key in flat:
            num = _num(flat[key])
            if num is not None:
                return num
    return None


def _num(value: Any) -> int | None:
    if value is None:
        return None
    try:
        return int(round(float(value)))
    except (TypeError, ValueError):
        return None


async def enrich(backlink) -> None:
    """Attach Moz metrics for the backlink's source domain into ``extra['moz']``.

    Best-effort: any failure is swallowed so the crawl/verdict is unaffected.
    """
    if not is_enabled():
        return
    try:
        metrics = await domain_metrics(backlink.source_domain)
    except Exception as exc:  # noqa: BLE001
        log.warning("moz_enrich_failed", domain=backlink.source_domain, error=repr(exc))
        return
    if not metrics:
        return
    extra = dict(backlink.extra or {})
    extra["moz"] = {**metrics, "fetched_at": datetime.now(timezone.utc).isoformat()}
    backlink.extra = extra
