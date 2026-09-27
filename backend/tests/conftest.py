"""Shared test fixtures.

Two things this file deliberately does NOT do:

1. It does not duplicate fixtures that also live in a test module. Two
   definitions of the same name meant the module-level one silently shadowed
   this one for the whole module, so everything here was dead code.

2. It does not rely on ASGITransport to exercise the lifespan. ASGITransport
   does not run startup/shutdown events, so anything that only happens in the
   lifespan -- pool creation, JSON logging setup, the graceful-shutdown
   teardown -- is invisible to every test that does not drive the lifespan
   explicitly. test_app_lifecycle.py does exactly that.
"""

import contextlib
import uuid

import pytest
import pytest_asyncio
from httpx import ASGITransport, AsyncClient

from app.core.config import get_settings
from app.main import app

_redis_reachable: bool | None = None


@pytest_asyncio.fixture
async def client():
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as ac:
        yield ac


@pytest.fixture
def sample_complaint():
    return {
        "text": "Water main burst on Mall Road since fajr, water entering ground floors",
        "location": "Mall Road, Lahore",
        "reporter_contact": "0300-1234567",
    }


@pytest.fixture
def unique_complaint():
    """A complaint payload guaranteed not to collide with another test.

    The triage content-hash cache is keyed on text+location, so a fixed payload
    means the second test to submit it gets a cache hit and never exercises the
    provider. Appending a uuid keeps every test on the real inference path.
    """
    return {
        "text": f"Streetlight has been out on this lane for four nights, number {uuid.uuid4().hex[:8]}",
        "location": "Model Town Block B, Lahore",
        "reporter_contact": None,
    }


@pytest_asyncio.fixture(autouse=True)
async def isolate_shared_redis_state():
    """Give every test a clean rate-limit bucket and a clean stats cache.

    The distributed rate limiter is keyed by client IP and the test client always
    presents the same address, so without this the whole suite draws from ONE
    shared token bucket. Once the first few tests had spent it, later tests
    started failing with 429 for reasons that had nothing to do with what they
    were testing -- order-dependent flakiness of exactly the kind that trains a
    team to ignore red.

    Only rate-limit and stats keys are touched. The triage cache is left alone
    on purpose, because cache-hit behaviour is itself under test.

    The provider singletons are also reset, not just the module-level client.
    get_rate_limiter() and get_cache_provider() return process-wide instances
    that cache their own `_client`, and pytest-asyncio gives each test a fresh
    event loop. A client built on a previous test's loop is dead by the time the
    next test awaits it, which surfaces as "Event loop is closed" inside the
    limiter's fail-open path -- so the test would quietly pass while testing
    nothing.
    """
    from app.core.dependencies import get_cache_provider, get_rate_limiter
    from app.providers.cache import close_redis_client, get_redis_client

    def _drop_cached_clients():
        for provider in (get_cache_provider(), get_rate_limiter()):
            provider._client = None

    global _redis_reachable
    if _redis_reachable is False:
        yield
        return

    try:
        redis = await get_redis_client()
        await redis.ping()
        _redis_reachable = True
    except Exception:
        # No Redis reachable: the unit tests still need to run.
        _redis_reachable = False
        yield
        return

    async def _reset():
        keys = []
        async for key in redis.scan_iter(match="ratelimit:*"):
            keys.append(key)
        async for key in redis.scan_iter(match="stats:*"):
            keys.append(key)
        if keys:
            await redis.delete(*keys)

    await _reset()
    try:
        yield
    finally:
        with contextlib.suppress(Exception):
            await _reset()
        with contextlib.suppress(Exception):
            await close_redis_client()
        _drop_cached_clients()


@pytest.fixture(autouse=True, scope="session")
def _deterministic_triage_provider():
    """Pin the provider for the whole session.

    With TRIAGE_PROVIDER=llm the same input can produce different output, and a
    flaky pipeline teaches a team to ignore red -- which is worse than having no
    pipeline. CI sets TRIAGE_PROVIDER=simulated for the same reason; this makes
    the guarantee hold even when someone runs the suite locally against a
    populated .env. Tests needing a specific provider override it themselves.
    """
    get_settings.cache_clear()
    settings = get_settings()
    original = settings.triage_provider
    settings.triage_provider = "simulated"
    yield
    settings.triage_provider = original
    get_settings.cache_clear()
