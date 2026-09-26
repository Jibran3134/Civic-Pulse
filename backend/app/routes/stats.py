from fastapi import APIRouter, Depends, Response

from app.core.dependencies import get_cache_provider, get_complaints_repository
from app.core.logging import get_logger
from app.providers.cache import CacheProvider
from app.repositories.complaints import ComplaintsRepository

logger = get_logger(__name__)

router = APIRouter()


@router.get("/stats")
async def get_stats(
    response: Response,
    cache: CacheProvider = Depends(get_cache_provider),
    repo: ComplaintsRepository = Depends(get_complaints_repository),
):
    cache_key = "stats:aggregates"
    cached_data, hit = await cache.get(cache_key)

    if hit and cached_data:
        response.headers["X-Cache"] = "HIT"
        return cached_data

    stats = await repo.get_stats()
    await cache.set(cache_key, stats, ttl=30)
    response.headers["X-Cache"] = "MISS"
    return stats
