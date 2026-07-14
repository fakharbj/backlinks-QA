"""Platform-wide external-API usage tracking + quota gates (Enterprise §3).

Every external call records one event into cheap Redis counters (hour + day
buckets, ~35-day TTL) — no migration, no hot-path DB writes, fail-open (a Redis
hiccup never breaks a crawl). The API dashboard reads these buckets; the QA
scheduler asks ``available(api)`` BEFORE dispatching so an exhausted quota
pauses work gracefully ("Waiting for API availability") instead of burning the
remaining day on doomed retries.

Known APIs: iproyal (crawl proxy), render (headless pool), serper (index),
moz / semrush (RapidAPI metrics), rdap (domain age), google_sheets, google_cse.
Limits come from the ``API_DAILY_LIMITS`` / ``API_HOURLY_LIMITS`` JSON knobs.
"""

from __future__ import annotations

import json
import time
from datetime import datetime, timedelta, timezone

from app.core.config import settings
from app.core.logging import get_logger

log = get_logger("services.api_usage")

KNOWN_APIS = (
    "iproyal", "render", "serper", "moz", "semrush", "rdap", "google_sheets", "google_cse",
)
_TTL = 35 * 24 * 3600  # keep ~5 weeks of hour buckets for the charts

# Redis key layout (all workspace-agnostic — quotas are per ACCOUNT, not tenant):
#   ls:apiu:{api}:h:{YYYYMMDDHH}:ok / :fail     counters
#   ls:apiu:{api}:h:{YYYYMMDDHH}:ms             summed duration (avg = ms/total)
#   ls:apiu:{api}:d:{YYYYMMDD}:ok / :fail
#   ls:apiu:{api}:last_ok / :last_err / :last_err_at   status strings


def _now() -> datetime:
    return datetime.now(timezone.utc)


def _hkey(api: str, dt: datetime) -> str:
    return f"ls:apiu:{api}:h:{dt.strftime('%Y%m%d%H')}"


def _dkey(api: str, dt: datetime) -> str:
    return f"ls:apiu:{api}:d:{dt.strftime('%Y%m%d')}"


def _limits(raw: str) -> dict[str, int]:
    try:
        data = json.loads(raw or "{}")
        return {str(k).lower(): int(v) for k, v in data.items() if int(v) > 0}
    except (ValueError, TypeError):
        return {}


def daily_limits() -> dict[str, int]:
    return _limits(settings.API_DAILY_LIMITS)


def hourly_limits() -> dict[str, int]:
    return _limits(settings.API_HOURLY_LIMITS)


# ── In-app limit configuration (admin-editable; overrides the .env defaults) ──
# Durable copy lives in the Setting KV (key "api_limits", primary workspace);
# a Redis mirror serves the hot paths (available() runs in workers with no ctx).
_LIMITS_KEY = "ls:apiu:limits"


async def effective_limits() -> tuple[dict[str, int], dict[str, int]]:
    """(daily, hourly) — the in-app configuration when set, else the .env JSON."""
    try:
        from app.core.redis import get_redis

        raw = await get_redis().get(_LIMITS_KEY)
        if raw:
            data = json.loads(raw if isinstance(raw, str) else raw.decode())
            return (
                {str(k).lower(): int(v) for k, v in (data.get("daily") or {}).items() if int(v) > 0},
                {str(k).lower(): int(v) for k, v in (data.get("hourly") or {}).items() if int(v) > 0},
            )
    except Exception:  # noqa: BLE001 — fall through to env
        pass
    return daily_limits(), hourly_limits()


async def store_limits(db, workspace_id, daily: dict[str, int], hourly: dict[str, int]) -> None:
    """Persist to the Setting KV (durable) + refresh the Redis mirror (hot path)."""
    from sqlalchemy import select as _select

    from app.models.settings import Setting

    clean = {
        "daily": {k.lower(): int(v) for k, v in daily.items() if k.lower() in KNOWN_APIS and int(v) > 0},
        "hourly": {k.lower(): int(v) for k, v in hourly.items() if k.lower() in KNOWN_APIS and int(v) > 0},
    }
    setting = (
        await db.execute(
            _select(Setting).where(Setting.workspace_id == workspace_id, Setting.key == "api_limits")
        )
    ).scalar_one_or_none()
    if setting is None:
        setting = Setting(workspace_id=workspace_id, key="api_limits", value=clean)
        db.add(setting)
    else:
        setting.value = clean
    await db.flush()
    try:
        from app.core.redis import get_redis

        await get_redis().set(_LIMITS_KEY, json.dumps(clean))
    except Exception:  # noqa: BLE001 — Setting row remains the durable copy
        pass


async def record(api: str, *, ok: bool, duration_ms: int | None = None, error: str | None = None) -> None:
    """Count one call (async contexts — workers, API). Fail-open."""
    api = api.lower()
    try:
        from app.core.redis import get_redis

        r = get_redis()
        now = _now()
        suffix = "ok" if ok else "fail"
        pipe = r.pipeline()
        for key in (f"{_hkey(api, now)}:{suffix}", f"{_dkey(api, now)}:{suffix}"):
            pipe.incr(key)
            pipe.expire(key, _TTL)
        if duration_ms is not None:
            pipe.incrby(f"{_hkey(api, now)}:ms", max(0, int(duration_ms)))
            pipe.expire(f"{_hkey(api, now)}:ms", _TTL)
        if ok:
            pipe.set(f"ls:apiu:{api}:last_ok", now.isoformat())
        else:
            pipe.set(f"ls:apiu:{api}:last_err", (error or "unknown")[:300])
            pipe.set(f"ls:apiu:{api}:last_err_at", now.isoformat())
        await pipe.execute()
    except Exception:  # noqa: BLE001 — usage tracking never breaks a request
        pass


def record_sync(api: str, *, ok: bool, duration_ms: int | None = None, error: str | None = None) -> None:
    """Sync twin for thread contexts (gspread reads under asyncio.to_thread)."""
    api = api.lower()
    try:
        import redis as _redis

        r = _redis.Redis.from_url(str(settings.REDIS_URL), socket_timeout=2)
        now = _now()
        suffix = "ok" if ok else "fail"
        pipe = r.pipeline()
        for key in (f"{_hkey(api, now)}:{suffix}", f"{_dkey(api, now)}:{suffix}"):
            pipe.incr(key)
            pipe.expire(key, _TTL)
        if duration_ms is not None:
            pipe.incrby(f"{_hkey(api, now)}:ms", max(0, int(duration_ms)))
            pipe.expire(f"{_hkey(api, now)}:ms", _TTL)
        if ok:
            pipe.set(f"ls:apiu:{api}:last_ok", now.isoformat())
        else:
            pipe.set(f"ls:apiu:{api}:last_err", (error or "unknown")[:300])
            pipe.set(f"ls:apiu:{api}:last_err_at", now.isoformat())
        pipe.execute()
    except Exception:  # noqa: BLE001
        pass


async def used_today(api: str) -> int:
    try:
        from app.core.redis import get_redis

        now = _now()
        vals = await get_redis().mget(f"{_dkey(api, now)}:ok", f"{_dkey(api, now)}:fail")
        return sum(int(v) for v in vals if v)
    except Exception:  # noqa: BLE001
        return 0


async def available(api: str) -> bool:
    """Quota gate: False when the configured daily/hourly limit is exhausted.
    Unconfigured APIs are always available (no silent throttling)."""
    api = api.lower()
    dlim, hlim = await effective_limits()
    day_limit = dlim.get(api)
    hour_limit = hlim.get(api)
    if not day_limit and not hour_limit:
        return True
    try:
        from app.core.redis import get_redis

        r = get_redis()
        now = _now()
        if day_limit:
            vals = await r.mget(f"{_dkey(api, now)}:ok", f"{_dkey(api, now)}:fail")
            if sum(int(v) for v in vals if v) >= day_limit:
                return False
        if hour_limit:
            vals = await r.mget(f"{_hkey(api, now)}:ok", f"{_hkey(api, now)}:fail")
            if sum(int(v) for v in vals if v) >= hour_limit:
                return False
    except Exception:  # noqa: BLE001 — fail-open: Redis down must not stop QA
        return True
    return True


async def snapshot() -> list[dict]:
    """Dashboard rows: one per known API with today's + this hour's numbers."""
    from app.core.redis import get_redis

    r = get_redis()
    now = _now()
    dlim, hlim = await effective_limits()
    out: list[dict] = []
    for api in KNOWN_APIS:
        keys = [
            f"{_dkey(api, now)}:ok", f"{_dkey(api, now)}:fail",
            f"{_hkey(api, now)}:ok", f"{_hkey(api, now)}:fail",
            f"{_hkey(api, now)}:ms",
            f"ls:apiu:{api}:last_ok", f"ls:apiu:{api}:last_err", f"ls:apiu:{api}:last_err_at",
        ]
        try:
            vals = await r.mget(*keys)
        except Exception:  # noqa: BLE001
            vals = [None] * len(keys)

        def _i(x) -> int:
            try:
                return int(x)
            except (TypeError, ValueError):
                return 0

        def _s(x) -> str | None:
            if x is None:
                return None
            return x.decode() if isinstance(x, (bytes, bytearray)) else str(x)

        d_ok, d_fail, h_ok, h_fail, h_ms = (_i(v) for v in vals[:5])
        last_ok, last_err, last_err_at = (_s(v) for v in vals[5:])
        day_total = d_ok + d_fail
        hour_total = h_ok + h_fail
        limit = dlim.get(api)
        remaining = max(0, limit - day_total) if limit else None
        status = "ok"
        if limit and day_total >= limit:
            status = "limit_reached"
        elif day_total and d_fail / day_total > 0.5:
            status = "erroring"
        elif day_total == 0:
            status = "idle"
        out.append({
            "api": api,
            "daily_limit": limit,
            "hourly_limit": hlim.get(api),
            "used_today": day_total,
            "remaining_today": remaining,
            "used_this_hour": hour_total,
            "ok_today": d_ok,
            "failed_today": d_fail,
            "success_rate": round(100.0 * d_ok / day_total, 1) if day_total else None,
            "avg_response_ms": round(h_ms / hour_total) if hour_total else None,
            "status": status,
            "last_success_at": last_ok,
            "last_error": last_err,
            "last_error_at": last_err_at,
        })
    return out


async def series(api: str, *, granularity: str = "hour", periods: int = 48) -> list[dict]:
    """Chart series: last N hour (or day) buckets, oldest first."""
    from app.core.redis import get_redis

    api = api.lower()
    granularity = "day" if granularity == "day" else "hour"
    # Bound the Redis MGET (3 keys per bucket): ≤14 days hourly, ≤35 daily.
    periods = max(1, min(periods, 336 if granularity == "hour" else 35))
    r = get_redis()
    now = _now()
    out: list[dict] = []
    step = timedelta(days=1) if granularity == "day" else timedelta(hours=1)
    keyfn = _dkey if granularity == "day" else _hkey
    points = [now - step * i for i in range(periods - 1, -1, -1)]
    keys: list[str] = []
    for dt in points:
        keys.extend((f"{keyfn(api, dt)}:ok", f"{keyfn(api, dt)}:fail", f"{keyfn(api, dt)}:ms"))
    try:
        vals = await r.mget(*keys)
    except Exception:  # noqa: BLE001
        vals = [None] * len(keys)
    for i, dt in enumerate(points):
        ok = int(vals[i * 3] or 0)
        fail = int(vals[i * 3 + 1] or 0)
        ms = int(vals[i * 3 + 2] or 0)
        out.append({
            "bucket": dt.strftime("%Y-%m-%d %H:00" if granularity == "hour" else "%Y-%m-%d"),
            "ok": ok,
            "fail": fail,
            "avg_ms": round(ms / (ok + fail)) if (ok + fail) else None,
        })
    return out
