from fastapi import APIRouter, Depends, Response

from app.core.dependencies import get_cache_provider, get_complaints_repository
from app.core.logging import get_logger
from app.providers.cache import CacheProvider
from app.repositories.complaints import ComplaintsRepository
from app.routes.complaints import STATS_CACHE_KEY

logger = get_logger(__name__)

router = APIRouter()


@router.get(
    "/stats",
    responses={
        200: {
            "description": "Aggregate counts by category and priority.",
            "headers": {
                "X-Cache": {
                    "description": "HIT when served from the Redis read-through cache, MISS on a miss.",
                    "schema": {"type": "string", "enum": ["HIT", "MISS"]},
                }
            },
        }
    },
)
async def get_stats(
    response: Response,
    cache: CacheProvider = Depends(get_cache_provider),
    repo: ComplaintsRepository = Depends(get_complaints_repository),
):
    """Aggregates, served through a Redis read-through cache.

    Two mechanisms keep this correct and neither replaces the other: the 30s
    TTL bounds how stale the snapshot can ever be if an invalidation is lost,
    and the explicit invalidate-on-write in create_complaint makes a freshly
    submitted complaint visible immediately. TTL alone shows operators stale
    data; invalidation alone leaks a stale entry forever if a write path is
    ever added that forgets.

    The key is imported from the complaints route rather than repeated as a
    literal. When the two sides each held their own copy of the string, a
    rename on one side silently stopped the invalidation from matching, and
    the only symptom was a CI job asserting MISS and seeing HIT.
    """
    cached_data, hit = await cache.get(STATS_CACHE_KEY)

    if hit and cached_data:
        response.headers["X-Cache"] = "HIT"
        return cached_data

    stats = await repo.get_stats()
    await cache.set(STATS_CACHE_KEY, stats, ttl=30)
    response.headers["X-Cache"] = "MISS"
    return stats
