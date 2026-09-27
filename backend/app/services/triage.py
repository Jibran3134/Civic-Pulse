import hashlib
import time
from collections import deque
from contextlib import suppress
from datetime import UTC, datetime
from typing import Any

from app.core.config import get_settings
from app.core.dependencies import get_cache_provider
from app.core.logging import get_logger
from app.providers.cache import CacheProvider
from app.providers.triage.base import TriageOutcome, TriageProvider
from app.providers.triage.factory import get_triage_provider

logger = get_logger(__name__)
settings = get_settings()

# In-memory fallback deque for recent outcomes if Redis is unavailable
_in_memory_recent_outcomes: deque[dict[str, Any]] = deque(maxlen=20)


class TriageService:
    def __init__(self, provider: TriageProvider | None = None, cache: CacheProvider | None = None):
        self._cache: CacheProvider | None = cache
        self._provider: TriageProvider | None = provider

    def _get_cache(self) -> CacheProvider:
        if self._cache is None:
            self._cache = get_cache_provider()
        return self._cache

    def _get_provider(self) -> TriageProvider:
        if self._provider is None:
            self._provider = get_triage_provider()
        return self._provider

    def _content_hash(self, text: str, location: str) -> str:
        """Normalized SHA-256 content hash for duplicate complaint detection."""
        content = f"{text.strip().lower()}|{location.strip().lower()}"
        return hashlib.sha256(content.encode("utf-8")).hexdigest()

    async def _record_outcome(self, outcome: dict[str, Any]) -> None:
        """Record triage outcome to Redis ring-buffer (last 20) and memory backup."""
        _in_memory_recent_outcomes.appendleft(outcome)
        try:
            cache = self._get_cache()
            await cache.lpush("triage:recent_outcomes", outcome, max_len=20)
        except Exception as e:
            logger.warning(f"Failed to record triage outcome in Redis: {e}")

    async def get_recent_outcomes(self, limit: int = 20) -> list[dict[str, Any]]:
        """Retrieve the last 20 triage outcomes."""
        try:
            cache = self._get_cache()
            items = await cache.lrange("triage:recent_outcomes", 0, limit - 1)
            if items:
                return items[:limit]
        except Exception as e:
            logger.warning(f"Failed to retrieve outcomes from Redis: {e}")

        return list(_in_memory_recent_outcomes)[:limit]

    async def get_cache_stats(self) -> dict[str, Any]:
        """Report measured cache hit rate for content-hash triage caching."""
        try:
            cache = self._get_cache()
            client = await cache._get_client()
            total_raw = await client.get("triage:stats:total_queries")
            hits_raw = await client.get("triage:stats:cache_hits")

            total = int(total_raw) if total_raw else 0
            hits = int(hits_raw) if hits_raw else 0
            hit_rate = round(hits / total, 4) if total > 0 else 0.0
            return {
                "total_queries": total,
                "cache_hits": hits,
                "cache_misses": total - hits,
                "hit_rate": hit_rate,
            }
        except Exception as e:
            logger.warning(f"Failed to fetch cache stats: {e}")
            return {"total_queries": 0, "cache_hits": 0, "cache_misses": 0, "hit_rate": 0.0}

    async def triage(
        self, text: str, location: str, complaint_id: str | None = None
    ) -> TriageOutcome:
        # Timer starts before cache lookup (measures full triage pipeline latency)
        start_time = time.perf_counter()
        cache = self._get_cache()
        content_hash = self._content_hash(text, location)
        cache_key = f"triage:cache:{content_hash}"

        # 1. Check content-hash cache in Redis (24 h TTL, §2.5 item 5)
        try:
            cached_data, hit = await cache.get(cache_key)
        except Exception:
            cached_data, hit = None, False

        if hit and cached_data:
            latency_ms = int((time.perf_counter() - start_time) * 1000)
            outcome = TriageOutcome(
                category=cached_data["category"],
                priority=cached_data["priority"],
                summary=cached_data["summary"],
                confidence=cached_data["confidence"],
                triaged_by=cached_data.get("triaged_by", "cache"),
                triage_latency_ms=latency_ms,
            )

            # Increment cache hit stats
            with suppress(Exception):
                await cache.incr("triage:stats:total_queries")
                await cache.incr("triage:stats:cache_hits")

            recorded_outcome = {
                "provider": outcome.triaged_by,
                "latency_ms": latency_ms,
                "fallback": False,
                "cache_hit": True,
                "timestamp": datetime.now(UTC).isoformat(),
            }
            await self._record_outcome(recorded_outcome)

            logger.info("Triage content-hash cache hit", extra={"hash": content_hash, "latency_ms": latency_ms})
            return outcome

        # Record total queries counter
        with suppress(Exception):
            await cache.incr("triage:stats:total_queries")

        # 2. Cache miss -> Invoke active TriageProvider
        provider = self._get_provider()
        is_fallback = False
        try:
            result = await provider.triage(text, location)
            triaged_by = provider.name
        except Exception as e:
            # 3. Fallback directly to RuleBasedTriage (§2.5 item 4 & Rubric F)
            # Structured JSON warning with complaint_id, provider, error_class (§2.6)
            is_fallback = True
            error_class = e.__class__.__name__
            logger.warning(
                "triage_fallback",
                extra={
                    "complaint_id": str(complaint_id) if complaint_id else "pre-persist",
                    "provider": provider.name,
                    "error_class": error_class,
                },
            )

            fallback_provider = get_triage_provider("rules")
            result = await fallback_provider.triage(text, location)
            triaged_by = "rules:fallback"

        latency_ms = int((time.perf_counter() - start_time) * 1000)
        outcome = TriageOutcome(
            category=result.category,
            priority=result.priority,
            summary=result.summary,
            confidence=result.confidence,
            triaged_by=triaged_by,
            triage_latency_ms=latency_ms,
        )

        # 4. Cache valid triage result with 24-hour TTL (86400s)
        try:
            cache_payload = {
                "category": result.category.value,
                "priority": result.priority.value,
                "summary": result.summary,
                "confidence": result.confidence,
                "triaged_by": triaged_by,
            }
            await cache.set(cache_key, cache_payload, ttl=86400)
        except Exception as e:
            logger.warning(f"Failed to cache triage result in Redis: {e}")

        # 5. Record outcome to recent outcomes list
        recorded_outcome = {
            "provider": triaged_by,
            "latency_ms": latency_ms,
            "fallback": is_fallback,
            "cache_hit": False,
            "timestamp": datetime.now(UTC).isoformat(),
        }
        await self._record_outcome(recorded_outcome)

        logger.info(
            "Triage completed",
            extra={
                "provider": triaged_by,
                "category": outcome.category.value,
                "priority": outcome.priority.value,
                "latency_ms": outcome.triage_latency_ms,
                "fallback": is_fallback,
            },
        )

        return outcome

