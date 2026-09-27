import json
from typing import Any

import redis.asyncio as redis

from app.core.config import get_settings
from app.core.logging import get_logger

logger = get_logger(__name__)
settings = get_settings()

_redis_client: redis.Redis | None = None


async def get_redis_client() -> redis.Redis:
    global _redis_client
    if _redis_client is None:
        _redis_client = redis.from_url(
            settings.redis_url,
            encoding="utf-8",
            decode_responses=True,
            max_connections=10,
        )
    return _redis_client


async def close_redis_client() -> None:
    global _redis_client
    if _redis_client is not None:
        await _redis_client.aclose()
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

    async def _get_client(self) -> redis.Redis:
        if self._client is None:
            self._client = await get_redis_client()
        return self._client

    async def check_limit(self, client_ip: str) -> tuple[bool, int]:
        """
        Token bucket rate limiter.
        Returns (allowed, retry_after_seconds).
        """
        client = await self._get_client()
        key = f"ratelimit:{client_ip}"

        try:
            pipe = client.pipeline()
            pipe.hgetall(key)
            pipe.ttl(key)
            results = await pipe.execute()

            bucket_data = results[0] or {}
            results[1]

            if not bucket_data:
                # First request - initialize bucket
                await client.hset(  # type: ignore[misc]
                    key,
                    mapping={
                        "tokens": str(settings.rate_limit_burst - 1),
                        "last_refill": "0",
                    },
                )
                await client.expire(key, settings.rate_limit_window_seconds)  # type: ignore[misc]
                return True, 0

            tokens = float(bucket_data.get("tokens", settings.rate_limit_burst))
            last_refill = float(bucket_data.get("last_refill", 0))

            import time
            now = time.time()
            elapsed = now - last_refill if last_refill > 0 else 0

            # Refill tokens based on elapsed time
            refill_rate = settings.rate_limit_requests / settings.rate_limit_window_seconds
            tokens = min(settings.rate_limit_burst, tokens + elapsed * refill_rate)

            if tokens >= 1:
                tokens -= 1
                await client.hset(key, mapping={"tokens": str(tokens), "last_refill": str(now)})  # type: ignore[misc]
                await client.expire(key, settings.rate_limit_window_seconds)  # type: ignore[misc]
                return True, 0

            # Calculate retry-after
            retry_after = int((1 - tokens) / refill_rate) + 1
            return False, retry_after

        except Exception as e:
            logger.error(f"Rate limiter check failed: {e}")
            # Fail open - allow request if Redis is down
            return True, 0

    async def health_check(self) -> bool:
        try:
            client = await self._get_client()
            await client.ping()
            return True
        except Exception:
            return False
