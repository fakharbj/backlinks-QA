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
    has_creds = bool(
        settings.MOZ_API_TOKEN
        or (settings.MOZ_ACCESS_ID and settings.MOZ_SECRET_KEY)
    )
    return bool(settings.MOZ_ENABLED and has_creds)


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
    """Call the Moz Links API v2 url_metrics endpoint for one domain."""
    payload = {"targets": [domain]}
    headers = {"Content-Type": "application/json"}
    auth: tuple[str, str] | None = None
    if settings.MOZ_API_TOKEN:
        headers["Authorization"] = f"Bearer {settings.MOZ_API_TOKEN}"
    elif settings.MOZ_ACCESS_ID and settings.MOZ_SECRET_KEY:
        auth = (settings.MOZ_ACCESS_ID, settings.MOZ_SECRET_KEY)
    try:
        async with httpx.AsyncClient(timeout=settings.MOZ_TIMEOUT_SECONDS) as client:
            resp = await client.post(
                settings.MOZ_API_ENDPOINT, json=payload, headers=headers, auth=auth
            )
        if resp.status_code != 200:
            log.warning("moz_http_error", domain=domain, status=resp.status_code,
                        body=resp.text[:300])
            return None
        data = resp.json()
    except Exception as exc:  # noqa: BLE001 - never let metrics break a crawl
        log.warning("moz_request_failed", domain=domain, error=repr(exc))
        return None

    results = data.get("results") or data.get("url_metrics") or []
    if not results:
        return None
    row = results[0]
    da = _num(row.get("domain_authority"))
    pa = _num(row.get("page_authority"))
    spam = _num(row.get("spam_score"))
    if da is None and pa is None and spam is None:
        return None
    return {"da": da, "pa": pa, "spam_score": spam}


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
