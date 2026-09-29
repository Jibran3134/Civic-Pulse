import json
import time
from typing import Any

import redis.asyncio as redis

from app.core.config import get_settings
from app.core.logging import get_logger

logger = get_logger(__name__)
settings = get_settings()

_redis_client: redis.Redis | None = None
_rate_limit_client: redis.Redis | None = None

# The whole read-modify-write of a token bucket has to happen inside Redis, on
# one connection, with no interleaving. Doing it from the client -- HGETALL,
# compute in Python, HSET -- is a textbook race: every concurrent caller reads
# the same token count, decides independently that a token is available, and
# all of them decrement from the value they read rather than the value that was
# actually written. Measured on this codebase before the fix, 20 concurrent
# requests against a bucket holding exactly 1 token were admitted 11, 19 and
# 20 times across three runs, i.e. the effective limit was roughly
# `configured_limit * concurrent_callers`, and unbounded if the connection pool
# ran dry.
#
# KEYS[1]  bucket key
# ARGV[1]  current unix time (passed in so the script needs no clock access)
# ARGV[2]  refill rate, tokens per second
# ARGV[3]  burst capacity
# ARGV[4]  window/TTL seconds
# Returns  { allowed (0|1), retry_after_seconds, tokens_remaining }
RATE_LIMIT_LUA = """
local key        = KEYS[1]
local now        = tonumber(ARGV[1])
local refill     = tonumber(ARGV[2])
local burst      = tonumber(ARGV[3])
local window     = tonumber(ARGV[4])

local bucket     = redis.call('HMGET', key, 'tokens', 'last_refill')
local tokens     = tonumber(bucket[1])
local last_refill = tonumber(bucket[2])

if tokens == nil then
    -- First request from this client. Bank a full bucket minus the token we
    -- are spending right now, and start the refill clock immediately so the
    -- second request already accrues from t=0.
    local remaining = burst - 1
    redis.call('HSET', key, 'tokens', remaining, 'last_refill', now)
    redis.call('EXPIRE', key, window)
    return {1, 0, remaining}
end

if last_refill == nil then
    last_refill = now
end

local elapsed = now - last_refill
if elapsed < 0 then
    elapsed = 0
end

tokens = math.min(burst, tokens + (elapsed * refill))

if tokens >= 1 then
    local remaining = tokens - 1
    redis.call('HSET', key, 'tokens', remaining, 'last_refill', now)
    redis.call('EXPIRE', key, window)
    return {1, 0, remaining}
end

-- Denied. Persist the tokens that refilled while we waited, otherwise the next
-- caller recomputes from a stale timestamp and the fractional progress is lost.
local retry_after = math.floor((1 - tokens) / refill) + 1
redis.call('HSET', key, 'tokens', tokens, 'last_refill', now)
redis.call('EXPIRE', key, window)
return {0, retry_after, tokens}
"""


async def get_redis_client() -> redis.Redis:
    """Connection pool for the cache job: stats snapshot, triage content-hash
    entries and the provider-outcome ring buffer. These are low volume and
    tolerate queueing."""
    global _redis_client
    if _redis_client is None:
        _redis_client = redis.from_url(
            settings.redis_url,
            encoding="utf-8",
            decode_responses=True,
            max_connections=10,
        )
    return _redis_client


async def get_rate_limit_client() -> redis.Redis:
    """Separate pool for the rate limiter.

    The limiter runs once per write request and, under load, is exactly the
    traffic a slow endpoint generates. Sharing the cache pool meant a burst
    against the limiter exhausted the same 10 connections the cache used, and
    the limiter's own error path admits every request -- so the pool exhaustion
    silently disabled the thing that was supposed to protect the database.

    This pool blocks rather than raising when it is saturated. The default
    ConnectionPool raises `Too many connections` the moment max_connections is
    exceeded, which lands in the same except branch as a genuine Redis outage
    and therefore fails open. Measured, 200 simultaneous checks against a
    50-connection pool admitted 155 requests against a burst of 5. Queuing is
    the correct behaviour here: each Lua evaluation is sub-millisecond, so
    waiting for a free connection is cheaper and stricter than admitting the
    request.
    """
    global _rate_limit_client
    if _rate_limit_client is None:
        pool = redis.BlockingConnectionPool.from_url(
            settings.redis_url,
            encoding="utf-8",
            decode_responses=True,
            max_connections=50,
            timeout=5,
        )
        _rate_limit_client = redis.Redis(connection_pool=pool)
    return _rate_limit_client


async def close_redis_client() -> None:
    global _redis_client, _rate_limit_client
    if _redis_client is not None:
        await _redis_client.aclose()
        _redis_client = None
    if _rate_limit_client is not None:
        await _rate_limit_client.aclose()
        _rate_limit_client = None
        _redis_client = None


async def redis_health_check() -> bool:
    """Fresh, one-shot Redis PING for the readiness probe.

    Deliberately does NOT reuse the module-level singleton. That client is bound
    to the event loop that first opened it, so under pytest-asyncio's
    function-scoped loops a cached client can be stale and report a false
    negative. A short-lived client costs one TCP handshake on a probe that runs
    every few seconds, which is a good trade for an honest answer.
    """
    client = redis.from_url(
        settings.redis_url,
        encoding="utf-8",
        decode_responses=True,
        socket_connect_timeout=2,
        socket_timeout=2,
    )
    try:
        await client.ping()
        return True
    except Exception:
        return False
    finally:
        await client.aclose()


class CacheProvider:
    def __init__(self):
        self._client: redis.Redis | None = None

    async def _get_client(self) -> redis.Redis:
        if self._client is None:
            self._client = await get_redis_client()
        return self._client

    async def get(self, key: str) -> tuple[Any | None, bool]:
        """Get value from cache. Returns (value, hit)."""
        client = await self._get_client()
        try:
            data = await client.get(key)
            if data is None:
                return None, False
            return json.loads(data), True
        except Exception as e:
            logger.warning(f"Cache get failed for key {key}: {e}")
            return None, False

    async def set(self, key: str, value: Any, ttl: int = 30) -> bool:
        """Set value in cache with TTL."""
        client = await self._get_client()
        try:
            await client.set(key, json.dumps(value, default=str), ex=ttl)
            return True
        except Exception as e:
            logger.warning(f"Cache set failed for key {key}: {e}")
            return False


    async def invalidate(self, key: str) -> bool:
        """Invalidate a cache key."""
        client = await self._get_client()
        try:
            await client.delete(key)
            return True
        except Exception as e:
            logger.warning(f"Cache invalidate failed for key {key}: {e}")
            return False

    async def incr(self, key: str) -> int:
        """Increment counter in cache."""
        client = await self._get_client()
        try:
            return await client.incr(key)
        except Exception as e:
            logger.warning(f"Cache incr failed for key {key}: {e}")
            return 0

    async def lpush(self, key: str, value: Any, max_len: int = 20) -> None:
        """Push value to list and trim to max_len."""
        client = await self._get_client()
        try:
            pipe = client.pipeline()
            pipe.lpush(key, json.dumps(value, default=str))
            if max_len > 0:
                pipe.ltrim(key, 0, max_len - 1)
            await pipe.execute()
        except Exception as e:
            logger.warning(f"Cache lpush failed for key {key}: {e}")

    async def lrange(self, key: str, start: int = 0, stop: int = -1) -> list[Any]:
        """Get range of values from list."""
        client = await self._get_client()
        try:
            # redis-py's stubs type lrange as returning `Awaitable[list] | list`
            # because the same method name exists on the sync client. Going
            # through one untyped reference is clearer than a per-line ignore.
            call: Any = client.lrange
            raw_items = await call(key, start, stop)
            items = []
            for item in raw_items:
                try:
                    items.append(json.loads(item))
                except Exception:
                    # Not every list element has to be JSON; pass it through
                    # rather than failing the whole read.
                    items.append(item)
            return items
        except Exception as e:
            logger.warning(f"Cache lrange failed for key {key}: {e}")
            return []

    async def health_check(self) -> bool:
        try:
            client = await self._get_client()
            await client.ping()
            return True
        except Exception:
            # Don't log error for expected connection issues during tests/shutdown
            return False



class RateLimiterProvider:
    def __init__(self):
        self._client: redis.Redis | None = None
        self._script = None

    async def _get_client(self) -> redis.Redis:
        if self._client is None:
            self._client = await get_rate_limit_client()
            # The RegisteredScript returned by register_script holds a
            # reference to the client it was registered on. Reset it here so
            # _get_script() re-registers on the new connection rather than
            # using a stale handle that would raise and fall into fail-open.
            self._script = None
        return self._client

    def _get_script(self, client: redis.Redis):
        if self._script is None:
            # register_script issues EVALSHA and transparently falls back to
            # EVAL when Redis replies NOSCRIPT, which is what happens if the
            # script cache is flushed underneath a running process.
            self._script = client.register_script(RATE_LIMIT_LUA)
        return self._script

    async def check_limit(self, client_ip: str) -> tuple[bool, int]:
        """
        Token bucket rate limiter, evaluated atomically inside Redis.
        Returns (allowed, retry_after_seconds).
        """
        if not settings.rate_limit_enabled:
            return True, 0

        try:
            # Acquiring the client is inside the try on purpose. An unreachable
            # Redis has to reach the fail-open / fail-closed decision below
            # rather than escaping as a 500, otherwise the switch only governs
            # script errors and not the outage it exists for.
            client = await self._get_client()
            key = f"ratelimit:{client_ip}"
            refill_rate = settings.rate_limit_requests / settings.rate_limit_window_seconds
            script = self._get_script(client)
            result = await script(
                keys=[key],
                args=[
                    time.time(),
                    refill_rate,
                    settings.rate_limit_burst,
                    settings.rate_limit_window_seconds,
                ],
            )
        except Exception as e:
            logger.error(f"Rate limiter check failed: {e}")
            # RATE_LIMIT_FAIL_CLOSED decides what an unreachable Redis means.
            # The default stays open because the LLM quota is independently
            # bounded by the provider timeout, the retry budget and the rules
            # fallback, so refusing writes would trade one outage for another.
            return (False, settings.rate_limit_window_seconds) if settings.rate_limit_fail_closed else (True, 0)

        allowed = int(result[0])
        retry_after = int(result[1])
        return bool(allowed), retry_after

    async def health_check(self) -> bool:
        try:
            client = await self._get_client()
            await client.ping()
            return True
        except Exception:
            return False
