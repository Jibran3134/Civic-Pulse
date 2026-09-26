import time
import hashlib
from typing import Optional

from app.core.config import get_settings
from app.core.dependencies import get_cache_provider
from app.core.logging import get_logger
from app.providers.cache import CacheProvider
from app.providers.triage.factory import get_triage_provider
from app.providers.triage.base import TriageProvider, TriageResult, Category, Priority


logger = get_logger(__name__)
settings = get_settings()


class TriageService:
    def __init__(self):
        self._cache: CacheProvider | None = None
        self._provider: TriageProvider | None = None

    def _get_cache(self) -> CacheProvider:
        if self._cache is None:
            self._cache = get_cache_provider()
        return self._cache

    def _get_provider(self) -> TriageProvider:
        if self._provider is None:
            self._provider = get_triage_provider()
        return self._provider

    def _content_hash(self, text: str, location: str) -> str:
        content = f"{text}|{location}"
        return hashlib.sha256(content.encode()).hexdigest()[:32]

    async def triage(self, text: str, location: str) -> TriageResult:
        start_time = time.perf_counter()

        cache = self._get_cache()
        content_hash = self._content_hash(text, location)
        cache_key = f"triage:{content_hash}"

        cached_result, hit = await cache.get(cache_key)
        if hit and cached_result:
            logger.info("Triage cache hit", extra={"hash": content_hash})
            result = TriageResult(**cached_result)
            result.triage_latency_ms = int((time.perf_counter() - start_time) * 1000)
            return result

        provider = self._get_provider()
        try:
            result = await provider.triage(text, location)
            result.triage_latency_ms = int((time.perf_counter() - start_time) * 1000)
        except Exception as e:
            logger.warning(f"Triage provider failed: {e}, falling back to rules")
            fallback_provider = get_triage_provider("rules")
            result = await fallback_provider.triage(text, location)
            result.triage_latency_ms = int((time.perf_counter() - start_time) * 1000)
            result.triaged_by = "rules:fallback"

        # Cache the result
        await cache.set(cache_key, result.model_dump(), ttl=86400)  # 24 hours

        logger.info(
            "Triage completed",
            extra={
                "provider": result.triaged_by,
                "category": result.category.value,
                "priority": result.priority.value,
                "latency_ms": result.triage_latency_ms,
            },
        )

        return result