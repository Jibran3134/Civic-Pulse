"""Tests for the distributed rate limiter on POST /api/complaints.

Scope note. The AI-layer fallback paths are covered in tests/test_triage.py
(Alishba's suite), including the assignment's mandatory
"provider always raises -> 201 with rules:fallback" case. This file deliberately
does not repeat them.

What is here instead is the part nobody had covered: the limiter itself. The
free LLM tier permits tens of requests per minute, so this endpoint is the one
place an unattended script can exhaust a whole day's quota, and the assignment is
explicit that the limiter must be *distributed* -- an in-process counter permits
N times the traffic the moment the HPA runs N replicas.

The limiter's Redis key is cleared between tests by the autouse fixture in
conftest.py. Without it the whole suite shares one token bucket, because every
test client presents the same address, and later tests start failing with 429
for reasons unrelated to what they are testing.
"""

import uuid

import pytest

from app.core.config import get_settings
from app.core.dependencies import get_rate_limiter
from app.routes.complaints import client_ip_from

pytestmark = pytest.mark.integration


def _payload() -> str:
    """A fresh payload each call, so the triage content cache is not involved."""
    return (
        '{"text":"Duplicate report of the burst main on this lane, ref '
        f'{uuid.uuid4().hex[:8]}",'
        '"location":"Mall Road, Lahore"}'
    )


async def _post(client, text: str):
    return await client.post(
        "/api/complaints",
        content=_payload(),
        headers={"Content-Type": "application/json"},
    )


class TestBurstExhaustion:
    async def test_burst_is_actually_bounded(self, client):
        """The limiter must deny within the configured burst, not permit freely."""
        settings = get_settings()
        allowed = 0
        denied = False

        for _ in range(settings.rate_limit_burst + 3):
            response = await _post(client, "x")
            if response.status_code == 201:
                allowed += 1
            elif response.status_code == 429:
                denied = True
                break

        assert denied, f"limiter allowed {allowed} consecutive requests without denying"
        # One request over the burst is possible if a refill landed mid-loop, so
        # the bound is burst+1 rather than exactly burst.
        assert allowed <= settings.rate_limit_burst + 1

    async def test_429_carries_retry_after(self, client, monkeypatch):
        async def denied(_client_ip: str):
            return False, 42

        # Patch the singleton's method, not get_rate_limiter itself. The route
        # declares `rate_limiter: RateLimiterProvider = Depends(get_rate_limiter)`,
        # and FastAPI resolves that dependency at import time, so rebinding the
        # module attribute has no effect on an already-wired route.
        monkeypatch.setattr(get_rate_limiter(), "check_limit", denied)

        response = await _post(client, "x")

        assert response.status_code == 429
        # Regression: the header used to be set on the injected `Response`
        # object, which FastAPI discards when it builds the error response from
        # the HTTPException. Clients got a bare 429 with no guidance.
        retry_after = response.headers.get("Retry-After")
        assert retry_after is not None, "429 sent without a Retry-After header"
        assert int(retry_after) == 42

    async def test_retry_after_is_a_positive_number_of_seconds(self, client, monkeypatch):
        async def denied(_client_ip: str):
            return False, 1

        monkeypatch.setattr(get_rate_limiter(), "check_limit", denied)
        response = await _post(client, "x")
        assert int(response.headers["Retry-After"]) > 0

    async def test_rate_limited_request_persists_nothing(self, client, monkeypatch):
        """The limiter runs before triage and before the insert.

        A rejected request must therefore cost nothing: no LLM call, no row.
        """
        before = (await client.get("/api/complaints", params={"page_size": 1})).json()["total"]

        async def denied(_client_ip: str):
            return False, 42

        monkeypatch.setattr(get_rate_limiter(), "check_limit", denied)
        denied_response = await _post(client, "x")
        assert denied_response.status_code == 429

        after = (await client.get("/api/complaints", params={"page_size": 1})).json()["total"]
        assert after == before

    async def test_limit_is_scoped_per_client_ip(self, client):
        """Two different callers must not share one bucket.

        This is the property that makes the limiter a per-caller limit rather
        than a global throughput cap, and it is what stops one noisy client from
        locking out everyone else.
        """
        settings = get_settings()
        first = {"X-Forwarded-For": "203.0.113.10"}
        second = {"X-Forwarded-For": "198.51.100.20"}

        # Drain the first caller's bucket.
        drained_first = False
        for _ in range(settings.rate_limit_burst + 3):
            r = await client.post(
                "/api/complaints",
                content=_payload(),
                headers={"Content-Type": "application/json", **first},
            )
            if r.status_code == 429:
                drained_first = True
                break
        assert drained_first, "could not drain the first caller's bucket"

        # A different caller must still be served.
        r = await client.post(
            "/api/complaints",
            content=_payload(),
            headers={"Content-Type": "application/json", **second},
        )
        assert r.status_code == 201, "a second client inherited the first client's exhausted bucket"


class TestClientIpExtraction:
    """The rate limiter keys on the client IP, so getting it wrong is not cosmetic.

    Behind the Ingress, request.client.host is the Ingress controller's pod IP.
    Keying on that would put every user on the internet into one shared token
    bucket, and one caller could deny service to everyone else.
    """

    class _FakeRequest:
        def __init__(self, headers, host):
            self.headers = headers
            self.client = type("C", (), {"host": host})()

    def test_prefers_the_leftmost_forwarded_entry(self):
        request = self._FakeRequest({"x-forwarded-for": "203.0.113.7, 10.0.0.1"}, "10.0.0.5")
        assert client_ip_from(request) == "203.0.113.7"

    def test_falls_back_to_the_peer_address(self):
        request = self._FakeRequest({}, "198.51.100.9")
        assert client_ip_from(request) == "198.51.100.9"

    def test_ignores_an_empty_forwarded_header(self):
        request = self._FakeRequest({"x-forwarded-for": "   "}, "198.51.100.9")
        assert client_ip_from(request) == "198.51.100.9"


class TestLimiterIsDistributed:
    """The limiter's state must live in Redis, not in the process.

    An in-process counter permits one bucket per replica, so the moment the HPA
    scales the backend to four pods the effective limit is four times the
    configured one. Asserting on the key is the cheapest way to keep that from
    being reintroduced.
    """

    async def test_bucket_is_stored_in_redis_under_the_client_ip(self, client):
        from app.core.dependencies import get_rate_limiter
        from app.providers.cache import get_redis_client

        limiter = get_rate_limiter()
        await limiter.check_limit("203.0.113.99")

        redis = await get_redis_client()
        assert await redis.exists("ratelimit:203.0.113.99"), (
            "the rate-limit bucket is not in Redis, so the limit is per-process "
            "and multiplies by the replica count"
        )

    async def test_fails_open_when_redis_is_unreachable(self, client, monkeypatch):
        """A cache outage must not take complaint intake down with it.

        The LLM quota is still protected by the provider's own timeout, retry
        budget and rules fallback, so allowing the request is the better failure
        than refusing every citizen's report.

        The failure is injected at the pipeline call rather than at
        _get_client: check_limit obtains the client before its try block, so an
        error there would propagate rather than fail open. Injecting at the
        command level exercises the fail-open path that actually exists.
        """
        limiter = get_rate_limiter()
        redis = await limiter._get_client()

        def boom(*_args, **_kwargs):
            raise ConnectionError("redis unreachable")

        monkeypatch.setattr(redis, "pipeline", boom)
        allowed, retry_after = await limiter.check_limit("203.0.113.5")
        assert (allowed, retry_after) == (True, 0)
