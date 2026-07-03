"""Source-site metrics — Similarweb (rank + traffic) or Moz (DA/PA/Spam).

These authority/traffic numbers describe the SOURCE domain of a backlink. They
can't be crawled, so we fetch them from an external API and cache per domain in
Redis for ``SITE_METRICS_CACHE_DAYS`` (they move slowly). The whole module is a
no-op unless ``SITE_METRICS_ENABLED`` and a key are set, and every failure is
swallowed so a crawl is never affected. Results are written into
``BacklinkRecord.extra['metrics']`` (the model's JSONB bag) — no migration.

Providers (``SITE_METRICS_PROVIDER``):
  • "similarweb"   GET  {endpoint}?domain=<domain>     → global_rank, monthly_visits, category
  • "moz_rapidapi" POST {endpoint} {"q": <domain>}      → da, pa, (spam)
  • "moz_official" POST {endpoint} {"targets":[domain]} → da, pa, spam_score
"""

from __future__ import annotations

import json
from datetime import datetime, timezone
from typing import Any

import httpx

from app.core.config import settings
from app.core.logging import get_logger
from app.core.redis import get_redis

log = get_logger("integrations.site_metrics")

_CACHE_PREFIX = "sitemetrics:"
_NEGATIVE = "__none__"


def is_enabled() -> bool:
    if not settings.SITE_METRICS_ENABLED:
        return False
    provider = settings.SITE_METRICS_PROVIDER
    if provider in ("similarweb", "moz_rapidapi"):
        return bool(settings.RAPIDAPI_KEY)
    return bool(
        settings.MOZ_API_TOKEN
        or (settings.MOZ_ACCESS_ID and settings.MOZ_SECRET_KEY)
    )


async def domain_metrics(domain: str) -> dict[str, Any] | None:
    """Return the cached/fetched metrics dict for a registrable domain, or None."""
    metrics, _origin = await domain_metrics_with_origin(domain)
    return metrics


async def domain_metrics_with_origin(domain: str) -> tuple[dict[str, Any] | None, str]:
    """Like :func:`domain_metrics` but also reports where the value came from:
    ``"cached"`` (reused, no API call), ``"fresh"`` (paid API call), or ``"none"``.
    The cached payload carries its ORIGINAL ``fetched_at`` so the UI can honestly
    say "checked N days ago" instead of pretending a cache hit is a new check."""
    if not is_enabled() or not domain:
        return None, "none"

    redis = get_redis()
    cache_key = f"{_CACHE_PREFIX}{settings.SITE_METRICS_PROVIDER}:{domain.lower()}"
    try:
        cached = await redis.get(cache_key)
    except Exception:  # noqa: BLE001 - cache is best-effort
        cached = None
    if cached == _NEGATIVE:
        return None, "cached"
    if cached:
        try:
            return json.loads(cached), "cached"
        except ValueError:
            pass

    metrics = await _fetch(domain)
    if metrics:
        metrics.setdefault("fetched_at", datetime.now(timezone.utc).isoformat())
    ttl = max(1, settings.SITE_METRICS_CACHE_DAYS) * 86400
    try:
        await redis.set(cache_key, json.dumps(metrics) if metrics else _NEGATIVE, ex=ttl)
    except Exception:  # noqa: BLE001
        pass
    return metrics, ("fresh" if metrics else "none")


async def _fetch(domain: str) -> dict[str, Any] | None:
    provider = settings.SITE_METRICS_PROVIDER
    try:
        if provider == "similarweb":
            return await _fetch_similarweb(domain)
        if provider == "moz_rapidapi":
            return await _fetch_moz_rapidapi(domain)
        return await _fetch_moz_official(domain)
    except Exception as exc:  # noqa: BLE001 - metrics must never break a crawl
        log.warning("site_metrics_failed", provider=provider, domain=domain, error=repr(exc))
        return None


async def _fetch_similarweb(domain: str) -> dict[str, Any] | None:
    headers = {
        "x-rapidapi-host": settings.SIMILARWEB_HOST,
        "x-rapidapi-key": settings.RAPIDAPI_KEY or "",
    }
    async with httpx.AsyncClient(timeout=settings.SITE_METRICS_TIMEOUT_SECONDS) as client:
        resp = await client.get(
            settings.SIMILARWEB_ENDPOINT, params={"domain": domain}, headers=headers
        )
    if resp.status_code != 200:
        log.warning("similarweb_http_error", domain=domain, status=resp.status_code,
                    body=resp.text[:300])
        return None
    data = resp.json()
    flat: dict[str, Any] = {}
    _flatten(data, flat)

    rank = _first(flat, ("globalrank", "global_rank", "rank"))
    visits = _first(flat, ("visits", "estimatedmonthlyvisits", "monthlyvisits",
                           "totalvisits", "monthly_visits"))
    category = _first_str(flat, ("category", "topcategory", "categoryname"))
    if rank is None and visits is None and category is None:
        log.warning("similarweb_unparsed", domain=domain, keys=list(flat)[:25])
        return None
    return {"provider": "similarweb", "global_rank": rank,
            "monthly_visits": visits, "category": category}


async def _fetch_moz_rapidapi(domain: str) -> dict[str, Any] | None:
    headers = {
        "Content-Type": "application/json",
        "x-rapidapi-host": settings.MOZ_RAPIDAPI_HOST,
        "x-rapidapi-key": settings.RAPIDAPI_KEY or "",
    }
    async with httpx.AsyncClient(timeout=settings.SITE_METRICS_TIMEOUT_SECONDS) as client:
        resp = await client.post(
            settings.MOZ_RAPIDAPI_ENDPOINT, json={"q": domain}, headers=headers
        )
    if resp.status_code != 200:
        log.warning("moz_rapidapi_http_error", domain=domain, status=resp.status_code,
                    body=resp.text[:300])
        return None
    return _parse_moz(resp.json(), domain)


async def _fetch_moz_official(domain: str) -> dict[str, Any] | None:
    headers = {"Content-Type": "application/json"}
    auth: tuple[str, str] | None = None
    if settings.MOZ_API_TOKEN:
        headers["Authorization"] = f"Bearer {settings.MOZ_API_TOKEN}"
    elif settings.MOZ_ACCESS_ID and settings.MOZ_SECRET_KEY:
        auth = (settings.MOZ_ACCESS_ID, settings.MOZ_SECRET_KEY)
    async with httpx.AsyncClient(timeout=settings.SITE_METRICS_TIMEOUT_SECONDS) as client:
        resp = await client.post(
            settings.MOZ_API_ENDPOINT, json={"targets": [domain]}, headers=headers, auth=auth
        )
    if resp.status_code != 200:
        log.warning("moz_official_http_error", domain=domain, status=resp.status_code,
                    body=resp.text[:300])
        return None
    return _parse_moz(resp.json(), domain)


def _parse_moz(data: Any, domain: str) -> dict[str, Any] | None:
    flat: dict[str, Any] = {}
    _flatten(data, flat)
    da = _first(flat, ("domain_authority", "da", "domainauthority"))
    pa = _first(flat, ("page_authority", "pa", "pageauthority"))
    spam = _first(flat, ("spam_score", "spam", "spamscore"))
    if da is None and pa is None and spam is None:
        log.warning("moz_unparsed", domain=domain, keys=list(flat)[:25])
        return None
    return {"provider": "moz", "da": da, "pa": pa, "spam_score": spam}


# ── Response helpers ──────────────────────────────────────────────────────────────
def _flatten(data: Any, out: dict[str, Any]) -> None:
    """Collect every scalar leaf keyed by its (lowercased) field name, first-wins."""
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


def _first_str(flat: dict[str, Any], keys: tuple[str, ...]) -> str | None:
    for key in keys:
        val = flat.get(key)
        if isinstance(val, str) and val.strip():
            return val.strip()[:80]
    return None


def _num(value: Any) -> int | None:
    if value is None or isinstance(value, bool):
        return None
    try:
        # Strip thousands separators / stray text from string numbers.
        if isinstance(value, str):
            cleaned = value.replace(",", "").strip()
            return int(round(float(cleaned)))
        return int(round(float(value)))
    except (TypeError, ValueError):
        return None


async def enrich(backlink) -> str:
    """Attach source-domain metrics into ``extra['metrics']`` (best-effort).
    Returns the origin ("cached" | "fresh" | "none") so callers can record the
    check history and count saved API calls."""
    if not is_enabled():
        return "none"
    try:
        metrics, origin = await domain_metrics_with_origin(backlink.source_domain)
    except Exception as exc:  # noqa: BLE001
        log.warning("site_metrics_enrich_failed", domain=backlink.source_domain, error=repr(exc))
        return "none"
    if not metrics:
        return origin
    extra = dict(backlink.extra or {})
    # Keep the payload's own fetched_at (true check time); stamp only if absent.
    extra["metrics"] = {
        "fetched_at": datetime.now(timezone.utc).isoformat(),
        **metrics,
    }
    backlink.extra = extra
    return origin
