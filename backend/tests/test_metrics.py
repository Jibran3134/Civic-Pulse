"""Tests for Prometheus metric wiring.

The four series the /metrics contract requires were previously DECLARED but
never incremented anywhere in the codebase, so /metrics served permanently
zero-valued series that looked implemented to anyone skimming. These tests
assert the metrics actually move, which is the only way that stays true.
"""

from app.core.metrics import (
    FALLBACK_COUNTER,
    REQUEST_COUNT,
    REQUEST_LATENCY,
    TRIAGE_COUNT,
    TRIAGE_LATENCY,
    record_triage,
)
from app.services.triage import TriageService


def _observation_count(histogram) -> float:
    """Total sample count for a histogram, via the public collect() API.

    Read through collect() rather than private attributes such as _sum/_count,
    which are not part of prometheus_client's supported surface and have moved
    between releases.
    """
    total = 0.0
    for metric in histogram.collect():
        for sample in metric.samples:
            if sample.name.endswith("_count"):
                total += sample.value
    return total


class TestMetricDefinitions:
    def test_all_four_contract_series_exist(self):
        # request count, request latency histogram, triage latency, fallback
        # counter -- the exact four the /metrics endpoint must expose.
        assert REQUEST_COUNT is not None
        assert REQUEST_LATENCY is not None
        assert TRIAGE_LATENCY is not None
        assert FALLBACK_COUNTER is not None

    def test_triage_histogram_buckets_cover_the_10s_cap(self):
        # The provider layer has a 10s hard cap, so a bucket set that stops at
        # the prometheus default of 10s puts every slow model call in +Inf and
        # makes the histogram useless for the question it exists to answer.
        # prometheus_client appends an implicit +Inf, hence the [:-1].
        assert 10.0 in TRIAGE_LATENCY._upper_bounds
        assert TRIAGE_LATENCY._upper_bounds[-2] == 10.0


class TestRecordTriage:
    def test_records_latency(self):
        before = _observation_count(TRIAGE_LATENCY)
        record_triage("llm:probe_latency", 0.25, fallback=False, cached=False)
        # A latency histogram that is never observed stays permanently empty,
        # which is what /metrics served before this was wired up.
        assert _observation_count(TRIAGE_LATENCY) == before + 1
        assert _observation_count(TRIAGE_LATENCY) > 0

    def test_fallback_increments_the_fallback_counter(self):
        before = FALLBACK_COUNTER.labels("llm:probe")._value.get()
        record_triage("llm:probe", 0.01, fallback=True, cached=False)
        after = FALLBACK_COUNTER.labels("llm:probe")._value.get()
        # A fallback that does not move this counter is invisible in a graph,
        # which is the one thing the observability surface exists to prevent.
        assert after == before + 1

    def test_non_fallback_does_not_increment_fallback_counter(self):
        before = FALLBACK_COUNTER.labels("llm:probe2")._value.get()
        record_triage("llm:probe2", 0.01, fallback=False, cached=False)
        assert FALLBACK_COUNTER.labels("llm:probe2")._value.get() == before

    def test_cache_hit_is_distinguishable_from_inference(self):
        before = TRIAGE_COUNT.labels("llm:probe3", "cached")._value.get()
        record_triage("llm:probe3", 0.001, fallback=False, cached=True)
        # Without this label a cache hit reports ~0ms and the dashboard makes
        # an instant model look like a fast one.
        assert TRIAGE_COUNT.labels("llm:probe3", "cached")._value.get() == before + 1




class _MemoryCache:
    """In-memory stand-in so these need no Redis.

    Mirrors the surface TriageService actually calls on CacheProvider.
    """

    def __init__(self):
        self.store = {}
        self.counters = {}
        self.lists = {}

    async def get(self, key):
        if key in self.store:
            return self.store[key], True
        return None, False

    async def set(self, key, value, ttl=30):
        self.store[key] = value
        return True

    async def incr(self, key):
        self.counters[key] = self.counters.get(key, 0) + 1
        return self.counters[key]

    async def lpush(self, key, value, max_len=20):
        self.lists.setdefault(key, []).insert(0, value)

    async def lrange(self, key, start=0, stop=-1):
        return self.lists.get(key, [])[start : stop + 1 if stop != -1 else None]


class _StubProvider:
    name = "llm:stub"

    def __init__(self):
        self.calls = 0

    async def triage(self, text, location):
        from app.providers.triage.base import Category, Priority, TriageOutcome

        self.calls += 1
        # triage_latency_ms is a required field on TriageOutcome (it subclasses
        # TriageResult and narrows triaged_by to a plain str), so a stub that
        # omits it fails validation and the service silently falls back to
        # rules -- which is exactly what happened the first time this was
        # written.
        return TriageOutcome(
            category=Category.WATER,
            priority=Priority.HIGH,
            summary="Burst water main flooding the street",
            confidence=0.9,
            triaged_by="llm:stub",
            triage_latency_ms=1,
        )


class _ExplodingProvider:
    name = "llm:exploding"

    def __init__(self):
        self.calls = 0

    async def triage(self, text, location):
        self.calls += 1
        raise RuntimeError("upstream 429 rate limited")


class TestServiceEmitsMetrics:
    """The service is the only layer that knows which of the three paths ran.

    Without these calls /metrics advertised triage_duration_seconds and
    triage_fallback_total as series that never moved.
    """

    async def test_successful_triage_records_latency(self):
        service = TriageService(provider=_StubProvider(), cache=_MemoryCache())
        before = _observation_count(TRIAGE_LATENCY)

        await service.triage("Burst water main on Mall Road", "Mall Road")

        assert _observation_count(TRIAGE_LATENCY) == before + 1, "triage latency was never observed"

    async def test_fallback_records_the_fallback_counter(self):
        provider = _ExplodingProvider()
        service = TriageService(provider=provider, cache=_MemoryCache())
        before = FALLBACK_COUNTER.labels(provider.name)._value.get()

        outcome = await service.triage("Burst water main on Mall Road", "Mall Road")

        # A fallback that does not move this counter is invisible in a graph,
        # which is the one thing the observability surface exists to prevent.
        assert FALLBACK_COUNTER.labels(provider.name)._value.get() == before + 1
        # And the fallback itself still produced a usable result, because
        # RuleBasedTriage is deterministic and always available.
        assert outcome.triaged_by == "rules:fallback"

    async def test_cache_hit_is_labelled_separately_from_inference(self):
        cache = _MemoryCache()
        service = TriageService(provider=_StubProvider(), cache=cache)

        await service.triage("Burst water main on Mall Road", "Mall Road")
        live_before = TRIAGE_COUNT.labels("llm:stub", "live")._value.get()
        cached_before = TRIAGE_COUNT.labels("llm:stub", "cached")._value.get()

        # Identical text+location hits the content-hash cache, so no inference.
        await service.triage("Burst water main on Mall Road", "Mall Road")

        # Without the cached label a ~1ms cache read and a multi-second model
        # call land in the same bucket and the chart says nothing.
        assert TRIAGE_COUNT.labels("llm:stub", "cached")._value.get() == cached_before + 1
        assert TRIAGE_COUNT.labels("llm:stub", "live")._value.get() == live_before
