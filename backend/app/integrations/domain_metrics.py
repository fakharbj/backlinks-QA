"""Per-domain third-party metrics (Phase 8, features 21/22/23).

Fetched PER SOURCE MAIN DOMAIN (never per URL) and stored in the DB (no Redis).
* Domain AGE — free RDAP (no key needed), so it works out of the box.
* Moz DA/PA — RapidAPI (needs ``RAPIDAPI_KEY`` + ``MOZ_RAPIDAPI_*``).
* Semrush AS / traffic / keywords — RapidAPI (needs key + ``SEMRUSH_RAPIDAPI_*``).

Anything without a key (or that errors) returns ``{}`` so analytics keep working
and the cell shows "—". The ``parse_*`` helpers are pure and unit-tested.
"""

from __future__ import annotations

from datetime import date, datetime, timezone

import httpx

from app.core.config import settings
from app.core.logging import get_logger

log = get_logger("integrations.domain_metrics")


def parse_rdap_created(payload: dict) -> date | None:
    """Pull the registration date out of an RDAP domain response."""
    for event in (payload or {}).get("events") or []:
        if str(event.get("eventAction", "")).lower() in ("registration", "registered"):
            raw = event.get("eventDate")
            if not raw:
                return None
            try:
                return datetime.fromisoformat(str(raw).replace("Z", "+00:00")).date()
            except ValueError:
                try:
                    return datetime.strptime(str(raw)[:10], "%Y-%m-%d").date()
                except ValueError:
                    return None
    return None


def parse_moz(payload: dict) -> dict:
    """Normalize a Moz RapidAPI response (shapes vary across proxies)."""
    if not isinstance(payload, dict):
        return {}
    da = payload.get("da") or payload.get("domain_authority") or payload.get("domainAuthority")
    pa = payload.get("pa") or payload.get("page_authority") or payload.get("pageAuthority")
    spam = payload.get("spam_score") or payload.get("spamScore")
    out: dict = {}
    if da is not None:
        out["da"] = int(float(da))
    if pa is not None:
        out["pa"] = int(float(pa))
    if spam is not None:
        out["spam_score"] = int(float(spam))
    return out


def parse_semrush(payload: dict) -> dict:
    """Normalize a Semrush RapidAPI response (AS / traffic / keywords)."""
    if not isinstance(payload, dict):
        return {}
    body = payload.get("data") if isinstance(payload.get("data"), dict) else payload
    as_ = body.get("authority_score") or body.get("authorityScore") or body.get("as")
    traffic = body.get("organic_traffic") or body.get("traffic") or body.get("monthly_traffic")
    kw = body.get("organic_keywords") or body.get("keywords") or body.get("keywords_count")
    out: dict = {}
    if as_ is not None:
        out["semrush_as"] = int(float(as_))
    if traffic is not None:
        out["semrush_traffic"] = int(float(traffic))
    if kw is not None:
        out["semrush_keywords"] = int(float(kw))
    return out


async def _fetch_age(domain: str, client: httpx.AsyncClient) -> dict:
    if not settings.DOMAIN_AGE_ENABLED:
        return {}
    url = settings.DOMAIN_AGE_RDAP_ENDPOINT.rstrip("/") + "/" + domain
    try:
        r = await client.get(url, headers={"Accept": "application/rdap+json"})
        if r.status_code != 200:
            return {}
        created = parse_rdap_created(r.json())
    except Exception as exc:  # noqa: BLE001 - metrics never break a request
        log.info("rdap_failed", domain=domain, error=repr(exc))
        return {}
    if created is None:
        return {}
    age = (datetime.now(timezone.utc).date() - created).days
    return {"domain_created_on": created, "domain_age_days": max(0, age)}


async def _fetch_moz(domain: str, client: httpx.AsyncClient) -> dict:
    if not settings.RAPIDAPI_KEY:
        return {}
    try:
        r = await client.post(
            settings.MOZ_RAPIDAPI_ENDPOINT,
            headers={
                "X-RapidAPI-Key": settings.RAPIDAPI_KEY,
                "X-RapidAPI-Host": settings.MOZ_RAPIDAPI_HOST,
            },
            json={"q": domain},
        )
        return parse_moz(r.json()) if r.status_code == 200 else {}
    except Exception as exc:  # noqa: BLE001
        log.info("moz_failed", domain=domain, error=repr(exc))
        return {}


async def _fetch_semrush(domain: str, client: httpx.AsyncClient) -> dict:
    if not (settings.RAPIDAPI_KEY and settings.SEMRUSH_RAPIDAPI_ENDPOINT):
        return {}
    try:
        r = await client.get(
            settings.SEMRUSH_RAPIDAPI_ENDPOINT,
            params={"domain": domain},
            headers={
                "X-RapidAPI-Key": settings.RAPIDAPI_KEY,
                "X-RapidAPI-Host": settings.SEMRUSH_RAPIDAPI_HOST,
            },
        )
        return parse_semrush(r.json()) if r.status_code == 200 else {}
    except Exception as exc:  # noqa: BLE001
        log.info("semrush_failed", domain=domain, error=repr(exc))
        return {}


async def fetch_all(domain: str, client: httpx.AsyncClient) -> dict:
    """All available metrics for one domain. Always returns a dict (maybe sparse)."""
    out: dict = {}
    out.update(await _fetch_age(domain, client))
    out.update(await _fetch_moz(domain, client))
    out.update(await _fetch_semrush(domain, client))
    if out:
        out["metrics_updated_at"] = datetime.now(timezone.utc)
    return out
