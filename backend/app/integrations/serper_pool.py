"""serper.dev API-key rotation pool.

Each free serper.dev key includes a one-time ~2,500-credit allowance. We keep an
ORDERED list of keys and always use the first one that still has credit — draining
one fully before moving to the next ("use one first"). When a key returns an
auth/credit error (401/402/403) it is retired into a Redis-backed "dead" set
(shared across the api / worker / beat processes) so every process skips it from
then on, and the next key takes over automatically. Add capacity by appending keys
to ``SERPER_API_KEYS`` and restarting — no code change.

Redis is best-effort: if it is unavailable we fall back to an in-process set so a
single process still rotates correctly for its own lifetime. Only key FINGERPRINTS
(a truncated sha256) are ever stored — never the raw keys.
"""

from __future__ import annotations

import hashlib

from app.core.config import settings
from app.core.logging import get_logger

log = get_logger("integrations.serper_pool")

_DEAD_SET = "ls:serper:dead"          # Redis set of retired key fingerprints
_USED_FMT = "ls:serper:used:{fp}"     # approx credits consumed per key (visibility)
_mem_dead: set[str] = set()           # in-process fallback when Redis is unavailable


def _fp(key: str) -> str:
    """Stable short fingerprint — lets us track a key in Redis without storing it."""
    return hashlib.sha256(key.encode()).hexdigest()[:16]


def all_keys() -> list[str]:
    """Ordered, de-duplicated key list: SERPER_API_KEYS (comma list) first, then the
    legacy single SERPER_API_KEY appended. Order defines the drain sequence."""
    raw: list[str] = []
    if settings.SERPER_API_KEYS:
        raw.extend(settings.SERPER_API_KEYS.split(","))
    if settings.SERPER_API_KEY:
        raw.append(settings.SERPER_API_KEY)
    out: list[str] = []
    seen: set[str] = set()
    for k in raw:
        k = k.strip()
        if k and k not in seen:
            seen.add(k)
            out.append(k)
    return out


async def _dead_fps() -> set[str]:
    try:
        from app.core.redis import get_redis

        vals = await get_redis().smembers(_DEAD_SET)
        return {v.decode() if isinstance(v, (bytes, bytearray)) else str(v) for v in (vals or set())}
    except Exception:  # noqa: BLE001 - fall back to in-process memory
        return set(_mem_dead)


async def active_key() -> str | None:
    """The first key that still has credit (not retired). None when all are exhausted."""
    dead = await _dead_fps()
    for k in all_keys():
        if _fp(k) not in dead:
            return k
    return None


async def mark_dead(key: str) -> None:
    """Retire a key (out of credit / invalid) so no process uses it again."""
    fp = _fp(key)
    _mem_dead.add(fp)
    try:
        from app.core.redis import get_redis

        await get_redis().sadd(_DEAD_SET, fp)
    except Exception:  # noqa: BLE001
        pass
    log.warning("serper_key_retired", fingerprint=fp, tail=key[-4:])


async def note_use(key: str, credits: int = 1) -> None:
    """Best-effort approximate usage counter (for the status readout, not authoritative)."""
    try:
        from app.core.redis import get_redis

        await get_redis().incrby(_USED_FMT.format(fp=_fp(key)), max(1, credits))
    except Exception:  # noqa: BLE001
        pass


async def reset() -> int:
    """Clear all retired/usage state (call after topping up credits). Returns key count."""
    _mem_dead.clear()
    keys = all_keys()
    try:
        from app.core.redis import get_redis

        r = get_redis()
        await r.delete(_DEAD_SET)
        for k in keys:
            await r.delete(_USED_FMT.format(fp=_fp(k)))
    except Exception:  # noqa: BLE001
        pass
    return len(keys)


async def status() -> dict:
    """Pool snapshot for monitoring: which key is active, which are exhausted, approx use."""
    dead = await _dead_fps()
    keys = all_keys()
    used: dict[str, int] = {}
    try:
        from app.core.redis import get_redis

        r = get_redis()
        for k in keys:
            v = await r.get(_USED_FMT.format(fp=_fp(k)))
            used[_fp(k)] = int(v) if v else 0
    except Exception:  # noqa: BLE001
        used = {}
    items: list[dict] = []
    active_assigned = False
    for i, k in enumerate(keys):
        fp = _fp(k)
        is_dead = fp in dead
        is_active = (not is_dead) and (not active_assigned)
        if is_active:
            active_assigned = True
        items.append({
            "index": i,
            "fingerprint": fp,
            "tail": k[-4:],
            "state": "exhausted" if is_dead else ("active" if is_active else "standby"),
            "approx_used": used.get(fp, 0),
        })
    return {
        "provider": settings.SERP_PROVIDER,
        "configured": len(keys),
        "exhausted": sum(1 for it in items if it["state"] == "exhausted"),
        "active_index": next((it["index"] for it in items if it["state"] == "active"), None),
        "per_key_free_credits": 2500,
        "keys": items,
    }
