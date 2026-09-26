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
        await _redis_client.close()
        _redis_client = None


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
            await client.setex(key, ttl, json.dumps(value, default=str))
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

    async def health_check(self) -> bool:
        try:
            client = await self._get_client()
            await client.ping()
            return True
        except Exception as e:
            logger.error(f"Redis health check failed: {e}")
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
                await client.hset(
                    key,
                    mapping={
                        "tokens": str(settings.rate_limit_burst - 1),
                        "last_refill": "0",
                    },
                )
                await client.expire(key, settings.rate_limit_window_seconds)
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
                await client.hset(key, mapping={"tokens": str(tokens), "last_refill": str(now)})
                await client.expire(key, settings.rate_limit_window_seconds)
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
        except Exception as e:
            logger.error(f"Rate limiter Redis health check failed: {e}")
            return False
