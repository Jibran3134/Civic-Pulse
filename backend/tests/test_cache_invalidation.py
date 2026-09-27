"""Regression tests for the stats cache contract.

The invalidation test here is not hypothetical. The cache-invalidation-on-write
step was silently missing from create_complaint after the AI layer merged, and
the only thing that noticed was the CI integration job asserting
`X-Cache: MISS` after a POST and getting `HIT`. These tests make the same
assertion cheap enough to run on every change.
"""

import uuid

import pytest

from app.routes.complaints import STATS_CACHE_KEY
from app.routes.stats import get_stats as stats_endpoint

pytestmark = pytest.mark.integration


class TestCacheKeyAgreement:
    def test_writer_and_reader_use_the_same_key(self):
        # The reader and the invalidator must agree on the key string. When
        # each held its own literal, a rename on one side made the delete a
        # silent no-op and the cached aggregates went stale for the full TTL.
        assert STATS_CACHE_KEY == "stats:aggregates"
        assert stats_endpoint is not None  # imported to prove the import resolves


class TestCacheInvalidationOnWrite:
    async def test_write_forces_the_next_read_to_miss(self, client):
        # Warm the cache: first call MISS, second HIT.
        first = await client.get("/api/stats")
        second = await client.get("/api/stats")
        assert first.headers["X-Cache"] == "MISS"
        assert second.headers["X-Cache"] == "HIT"

        # Now write. The next read MUST miss, because the aggregates just
        # changed. Without an explicit delete the snapshot survives for the
        # full 30s TTL, which is precisely the window in which an operator
        # would submit a duplicate report of the same problem.
        payload = {
            "text": f"Overflowing drain blocking the lane, ref {uuid.uuid4().hex[:8]}",
            "location": "Sabzazar, Lahore",
        }
        created = await client.post("/api/complaints", json=payload)
        assert created.status_code == 201

        after_write = await client.get("/api/stats")
        assert after_write.headers["X-Cache"] == "MISS", (
            "a complaint write did not invalidate the stats cache; the dashboard "
            "would show stale aggregates for up to the full TTL"
        )

    async def test_invalidated_snapshot_reflects_the_new_complaint(self, client):
        before = (await client.get("/api/stats")).json()
        before_total = sum(before["by_category"].values())

        await client.post(
            "/api/complaints",
            json={
                "text": f"Streetlight dark on the whole lane, ref {uuid.uuid4().hex[:8]}",
                "location": "Model Town, Lahore",
            },
        )

        after = (await client.get("/api/stats")).json()
        after_total = sum(after["by_category"].values())
        # Not just a MISS: the recomputed snapshot must actually contain the
        # new row, otherwise the header could flip for an unrelated reason.
        assert after_total == before_total + 1

    async def test_cache_still_works_after_invalidation(self, client):
        # A broken invalidation that also poisoned the cache would leave the
        # endpoint permanently returning MISS.
        await client.get("/api/stats")
        await client.post(
            "/api/complaints",
            json={
                "text": f"Power cut in the whole block, ref {uuid.uuid4().hex[:8]}",
                "location": "Askari 10, Lahore",
            },
        )
        assert (await client.get("/api/stats")).headers["X-Cache"] == "MISS"
        assert (await client.get("/api/stats")).headers["X-Cache"] == "HIT"


class TestRetryAfterHeader:
    async def test_429_carries_a_usable_retry_after(self, client, monkeypatch):
        from app.core.dependencies import get_rate_limiter

        async def denied(_client_ip: str):
            return False, 42

        monkeypatch.setattr(get_rate_limiter(), "check_limit", denied)

        response = await client.post(
            "/api/complaints",
            json={"text": "Burst water main flooding the street badly", "location": "Mall Road"},
        )

        assert response.status_code == 429
        # Regression: the header used to be set on the injected `Response`
        # object, which FastAPI discards when it builds the error response
        # from the HTTPException. Clients got a bare 429 with no guidance.
        retry_after = response.headers.get("Retry-After")
        assert retry_after is not None, "429 sent without a Retry-After header"
        assert int(retry_after) == 42
