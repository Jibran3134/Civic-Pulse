"""Statistics, served through a read-through cache.

Section 2.2 assigns "statistics" to services/. The read-through algorithm --
check the cache, fall back to the repository on a miss, populate the cache,
and report which happened -- is a policy decision, not an HTTP concern. It
lived in the route handler, which meant the cache TTL, the hit/miss semantics
and the repository call were all decided in the web layer.

Moving it here also puts the X-Cache outcome in the return value rather than in
a mutated response object, so a caller can use the data without the header
being set for them.

Two independent mechanisms keep the result correct and neither replaces the
other: the TTL bounds how stale the snapshot can ever become if an invalidation
is lost, and the explicit invalidate-on-write in create_complaint makes a
freshly submitted complaint visible immediately. TTL alone shows operators
stale data; invalidation alone leaks a stale entry forever if a write path is
ever added that forgets.

The cache key is defined once, in app.services.statistics, and imported by the
complaints route that invalidates it. When the two sides each held their own
copy of the string, a rename on one side silently stopped the invalidation
from matching, and the only symptom was a CI job asserting MISS and seeing HIT.
"""

from dataclasses import dataclass
from typing import Any

from app.core.config import get_settings
from app.core.logging import get_logger
from app.providers.cache import CacheProvider
from app.repositories.complaints import ComplaintsRepository

logger = get_logger(__name__)
settings = get_settings()

# Single definition. The write path imports this to invalidate.
STATS_CACHE_KEY = "stats:aggregates"


@dataclass
class StatsResult:
    """Aggregates plus whether they came from the cache.

    Returned as a value rather than written into a FastAPI Response, so the
    header is the caller's decision to make.
    """

    stats: dict[str, Any]
    from_cache: bool

    @property
    def cache_state(self) -> str:
        return "HIT" if self.from_cache else "MISS"


class StatisticsService:
    def __init__(self, repo: ComplaintsRepository, cache: CacheProvider) -> None:
        self._repo = repo
        self._cache = cache

    async def get_stats(self) -> StatsResult:
        """Read-through. Cache first; on a miss compute and populate."""
        cached_data, hit = await self._cache.get(STATS_CACHE_KEY)

        if hit and cached_data:
            return StatsResult(stats=cached_data, from_cache=True)

        stats = await self._repo.get_stats()
        await self._cache.set(
            STATS_CACHE_KEY, stats, ttl=settings.stats_cache_ttl_seconds
        )
        return StatsResult(stats=stats, from_cache=False)

    async def invalidate(self) -> bool:
        """Drop the snapshot. Called on every write.

        Not optional: a read-through cache with a TTL but no invalidation
        shows an operator a complaint they just submitted as missing for up to
        the TTL, which is exactly the window in which somebody files a
        duplicate report.
        """
        return await self._cache.invalidate(STATS_CACHE_KEY)
