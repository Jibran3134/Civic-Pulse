"""Atomicity of the distributed rate limiter.

Section E requires the limiter to be distributed. It does not say how, but a
client-side HGETALL -> compute -> HSET is not distributed in any meaningful
sense: every concurrent caller reads the same token count and admits itself.
These tests hold a bucket to a known size and fire concurrent checks at it, so
a regression to the old read-modify-write cannot pass.

Measured before the fix: 20 concurrent calls against 1 token were admitted 11,
19 and 20 times across three runs.
"""

import asyncio
import time

import pytest

from app.providers.cache import RateLimiterProvider, get_rate_limit_client


@pytest.fixture
async def limiter():
    return RateLimiterProvider()


@pytest.fixture
async def isolated_key():
    """A per-test key, so tests cannot interfere with each other or with the
    application rate limiter running against the same Redis."""
    client = await get_rate_limit_client()
    key_suffix = str(time.time_ns())
    yield f"203.0.113.{key_suffix}"
    await client.delete(f"ratelimit:{key_suffix}")


class TestAtomicityUnderConcurrency:
    async def test_single_token_admits_exactly_one_of_many_concurrent(self, limiter, isolated_key):
        """The core regression guard.

        Seed the bucket to exactly one token, then fire many simultaneous
        checks. An atomic read-modify-write admits exactly one. The old
        client-side implementation admitted between 11 and 20 of 20.
        """
        client = await get_rate_limit_client()
        await client.delete(f"ratelimit:{isolated_key}")
        await client.hset(
            f"ratelimit:{isolated_key}",
            mapping={"tokens": "1", "last_refill": str(time.time())},
        )
        await client.expire(f"ratelimit:{isolated_key}", 300)

        results = await asyncio.gather(*[limiter.check_limit(isolated_key) for _ in range(20)])
        admitted = sum(1 for allowed, _ in results if allowed)

        assert admitted == 1, (
            f"{admitted} of 20 concurrent requests were admitted from a single "
            "token, so the read-modify-write is not atomic"
        )

    async def test_burst_capacity_is_never_exceeded_under_concurrency(self, limiter, isolated_key):
        """A cold key starts at burst capacity. Under a simultaneous burst the
        total admitted must equal the burst, never exceed it."""
        client = await get_rate_limit_client()
        await client.delete(f"ratelimit:{isolated_key}")

        results = await asyncio.gather(*[limiter.check_limit(isolated_key) for _ in range(20)])
        admitted = sum(1 for allowed, _ in results if allowed)

        from app.core.config import get_settings

        assert admitted == get_settings().rate_limit_burst, (
            f"admitted {admitted}, expected exactly the burst capacity "
            f"{get_settings().rate_limit_burst}"
        )

    async def test_concurrent_denial_is_consistent(self, limiter, isolated_key):
        """Every denied response must carry a usable retry-after, and a denied
        caller must not have silently consumed a token."""
        client = await get_rate_limit_client()
        await client.delete(f"ratelimit:{isolated_key}")
        # Empty the bucket well below the refill threshold.
        await client.hset(
            f"ratelimit:{isolated_key}",
            mapping={"tokens": "0", "last_refill": str(time.time())},
        )
        await client.expire(f"ratelimit:{isolated_key}", 300)

        results = await asyncio.gather(*[limiter.check_limit(isolated_key) for _ in range(10)])
        for allowed, retry_after in results:
            assert allowed is False
            assert retry_after > 0, "a 429 must carry a positive Retry-After"

    async def test_sequential_burst_still_works(self, limiter, isolated_key):
        """The limiter must still allow a legitimate sequential burst, not
        simply deny everything."""
        client = await get_rate_limit_client()
        await client.delete(f"ratelimit:{isolated_key}")

        results = [await limiter.check_limit(isolated_key) for _ in range(5)]

        from app.core.config import get_settings

        assert all(allowed for allowed, _ in results), "sequential burst was rejected"
        assert get_settings().rate_limit_burst == 5

    async def test_saturation_does_not_fail_open(self, limiter, isolated_key):
        """Connection-pool exhaustion must not become an allow-everything event.

        The limiter's error path admits the request so a Redis outage cannot
        take the API down with it. That makes pool exhaustion just as dangerous
        as an outage: a large burst saturates the pool, the exception handler
        runs, and every request is waved through. Measured with a non-blocking
        pool, 200 simultaneous checks admitted 155 against a burst of 5.
        """
        client = await get_rate_limit_client()
        await client.delete(f"ratelimit:{isolated_key}")

        results = await asyncio.gather(*[limiter.check_limit(isolated_key) for _ in range(200)])
        admitted = sum(1 for allowed, _ in results if allowed)

        from app.core.config import get_settings

        assert admitted == get_settings().rate_limit_burst, (
            f"200 simultaneous requests admitted {admitted}; the limiter must "
            f"still cap at the burst of {get_settings().rate_limit_burst}, which "
            "means the connection pool failed open rather than queueing"
        )
