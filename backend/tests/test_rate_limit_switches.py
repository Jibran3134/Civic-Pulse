"""The two operational switches the rate limiter exposes.

Both settings existed in Settings for a long time and nothing read them, so a
deployment could set RATE_LIMIT_FAIL_CLOSED=true and get exactly the same
behaviour. These tests pin the switches to the behaviour they now control.
"""

import pytest

from app.providers.cache import RateLimiterProvider


@pytest.fixture
def limiter():
    return RateLimiterProvider()


class TestRateLimitSwitches:
    async def test_disabled_limiter_admits_everything(self, limiter, monkeypatch):
        import app.providers.cache as cache_module

        settings = cache_module.settings
        monkeypatch.setattr(settings, "rate_limit_enabled", False, raising=False)

        results = [await limiter.check_limit("203.0.113.120") for _ in range(50)]

        assert all(allowed for allowed, _ in results), (
            "RATE_LIMIT_ENABLED=false must not be able to reject anything"
        )

    async def test_enabled_limiter_does_reject(self, limiter):
        """The mirror image, so the first test cannot pass vacuously."""
        import app.providers.cache as cache_module

        assert cache_module.settings.rate_limit_enabled is True
        results = [await limiter.check_limit("203.0.113.121") for _ in range(50)]
        assert not all(allowed for allowed, _ in results), (
            "with the limiter enabled, 50 sequential requests must include rejections"
        )

    async def test_redis_failure_fails_open_by_default(self, limiter, monkeypatch):
        """Default behaviour: a Redis outage must not take writes down.

        The LLM quota is bounded independently by the provider timeout, the
        single retry budget and the rules fallback, so refusing writes during a
        cache outage trades a rate-limit breach for a total API outage.
        """
        import app.providers.cache as cache_module

        settings = cache_module.settings
        monkeypatch.setattr(settings, "rate_limit_fail_closed", False, raising=False)

        async def boom():
            raise ConnectionError("redis is down")

        monkeypatch.setattr(limiter, "_get_client", boom)

        allowed, retry_after = await limiter.check_limit("203.0.113.122")
        assert allowed is True
        assert retry_after == 0

    async def test_redis_failure_fails_closed_when_configured(self, limiter, monkeypatch):
        """RATE_LIMIT_FAIL_CLOSED=true must actually reject."""
        import app.providers.cache as cache_module

        settings = cache_module.settings
        monkeypatch.setattr(settings, "rate_limit_fail_closed", True, raising=False)

        async def boom():
            raise ConnectionError("redis is down")

        monkeypatch.setattr(limiter, "_get_client", boom)

        allowed, retry_after = await limiter.check_limit("203.0.113.123")
        assert allowed is False
        assert retry_after > 0, "a fail-closed rejection needs a usable Retry-After"
