"""Tests for settings and the CORS/probe-critical configuration.

Small, but this is the file that decides whether the container is talking to
the right database, and a wrong default here is a production outage rather
than a test failure.
"""

import pytest

from app.core.config import Settings, get_settings


class TestSettings:
    def test_reads_from_environment(self, monkeypatch):
        monkeypatch.setenv("DATABASE_URL", "postgresql://u:p@db:5432/x")
        monkeypatch.setenv("REDIS_URL", "redis://cache:6379/1")
        settings = Settings()
        assert settings.database_url == "postgresql://u:p@db:5432/x"
        assert settings.redis_url == "redis://cache:6379/1"

    def test_extra_env_vars_are_ignored(self, monkeypatch):
        # Containers receive a lot of environment they did not ask for;
        # pydantic-settings must not refuse to start because of it.
        monkeypatch.setenv("SOME_UNRELATED_RUNTIME_VAR", "1")
        assert Settings().app_name == "CivicPulse"

    @pytest.mark.parametrize(
        ("value", "expected"),
        [("production", True), ("PRODUCTION", True), ("development", False), ("staging", False)],
    )
    def test_is_production(self, value, expected):
        assert Settings(environment=value).is_production is expected

    def test_ttl_is_configurable_not_hardcoded(self):
        # The stats TTL used to be a literal 30 in the route, so the setting
        # existed but did nothing.
        assert Settings(STATS_CACHE_TTL=5).stats_cache_ttl_seconds == 5

    def test_stats_cache_ttl_defaults_to_the_contracted_30s(self):
        # The assignment fixes this at 30 seconds: long enough to absorb a
        # burst of dashboard refreshes, short enough that a complaint an
        # operator just submitted is not hidden for long.
        assert Settings().stats_cache_ttl_seconds == 30

    def test_api_key_never_has_a_usable_default(self):
        # A key comes from the environment, a Kubernetes Secret or GitHub
        # Secrets -- never from a file in the repository.
        assert Settings().groq_api_key == ""


class TestCorsOrigins:
    def test_empty_by_default(self):
        # The production topology is same-origin behind nginx, which proxies
        # /api. The safe baseline is to allow no cross-origin access at all.
        assert Settings().cors_origins == []

    def test_parses_comma_separated_list(self):
        settings = Settings(CORS_ORIGINS="https://a.example, https://b.example")
        assert settings.cors_origins == ["https://a.example", "https://b.example"]

    def test_strips_whitespace_and_drops_empties(self):
        settings = Settings(CORS_ORIGINS=" https://a.example , ,https://b.example ")
        assert settings.cors_origins == ["https://a.example", "https://b.example"]


class TestRateLimitSettings:
    def test_refill_rate_is_derivable(self):
        settings = Settings(RATE_LIMIT_REQUESTS=10, RATE_LIMIT_WINDOW=60)
        # 10 requests per 60s is the sustained rate; the burst is the bucket
        # capacity. Both are needed for the token bucket to be well-formed.
        assert settings.rate_limit_requests / settings.rate_limit_window_seconds == pytest.approx(1 / 6)
        assert settings.rate_limit_burst >= 1

    def test_burst_is_smaller_than_or_equal_to_window_capacity(self):
        settings = Settings()
        # A burst larger than the sustained rate allows means a client can
        # burst far more than the configured limit intends.
        assert settings.rate_limit_burst <= settings.rate_limit_requests


class TestSettingsCache:
    def test_get_settings_is_cached(self):
        # get_settings is called at import time by a dozen modules. Rebuilding
        # it per call would be wasteful and, worse, could return different
        # values within one request.
        assert get_settings() is get_settings()
