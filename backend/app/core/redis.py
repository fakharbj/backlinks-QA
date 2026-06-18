"""Shared async Redis client + small primitives (denylist, token bucket, cache).

The token-bucket refill is implemented as a Lua script so the check-and-consume
is atomic across all workers hitting the same domain (Arch §7).
"""

from __future__ import annotations

import time
from typing import Final

import redis.asyncio as aioredis

from app.core.config import settings

_pool: aioredis.Redis | None = None

# Atomic token bucket: KEYS[1]=bucket key, ARGV=[rate, capacity, now, requested]
# Returns 1 if allowed (and consumes), else 0. Stores {tokens, ts} as a hash.
_TOKEN_BUCKET_LUA: Final[str] = """
local key = KEYS[1]
local rate = tonumber(ARGV[1])
local capacity = tonumber(ARGV[2])
local now = tonumber(ARGV[3])
local requested = tonumber(ARGV[4])
local data = redis.call('HMGET', key, 'tokens', 'ts')
local tokens = tonumber(data[1])
local ts = tonumber(data[2])
if tokens == nil then tokens = capacity; ts = now end
local delta = math.max(0, now - ts)
tokens = math.min(capacity, tokens + delta * rate)
local allowed = 0
if tokens >= requested then
  allowed = 1
  tokens = tokens - requested
end
redis.call('HMSET', key, 'tokens', tokens, 'ts', now)
redis.call('EXPIRE', key, math.ceil(capacity / rate) + 60)
return allowed
"""


def get_redis() -> aioredis.Redis:
    global _pool
    if _pool is None:
        _pool = aioredis.from_url(
            str(settings.REDIS_URL),
            encoding="utf-8",
            decode_responses=True,
            max_connections=100,
        )
    return _pool


async def close_redis() -> None:
    global _pool
    if _pool is not None:
        await _pool.aclose()
        _pool = None


# ── JWT refresh denylist ────────────────────────────────────────────────────────
async def revoke_jti(jti: str, ttl_seconds: int) -> None:
    await get_redis().set(f"jwt:revoked:{jti}", "1", ex=max(ttl_seconds, 1))


async def is_jti_revoked(jti: str) -> bool:
    return await get_redis().exists(f"jwt:revoked:{jti}") == 1


# ── Per-domain token bucket ─────────────────────────────────────────────────────
async def allow_domain_request(
    domain: str, *, rate: float, capacity: int, requested: int = 1
) -> bool:
    r = get_redis()
    allowed = await r.eval(
        _TOKEN_BUCKET_LUA,
        1,
        f"rl:{domain}",
        rate,
        capacity,
        time.time(),
        requested,
    )
    return bool(allowed)


# ── Per-domain circuit breaker ──────────────────────────────────────────────────
async def record_domain_failure(domain: str, *, threshold: int, cooldown: int) -> bool:
    """Increment failure counter; open the breaker (returns True) past threshold."""
    r = get_redis()
    key = f"cb:{domain}"
    count = await r.incr(key)
    if count == 1:
        await r.expire(key, cooldown)
    if count >= threshold:
        await r.set(f"cb:open:{domain}", "1", ex=cooldown)
        return True
    return False


async def reset_domain_failures(domain: str) -> None:
    await get_redis().delete(f"cb:{domain}", f"cb:open:{domain}")


async def is_domain_circuit_open(domain: str) -> bool:
    return await get_redis().exists(f"cb:open:{domain}") == 1
