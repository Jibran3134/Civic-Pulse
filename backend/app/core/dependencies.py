from collections.abc import AsyncGenerator

from fastapi import Depends, Request

from app.core.database import get_connection
from app.core.logging import get_logger
from app.providers.cache import CacheProvider, RateLimiterProvider
from app.providers.triage.factory import get_triage_provider
from app.repositories.complaints import ComplaintsRepository
from app.services.statistics import StatisticsService

logger = get_logger(__name__)


# Cache and rate limiter are stateless, return directly
_cache_provider: CacheProvider | None = None
_rate_limiter: RateLimiterProvider | None = None


async def get_complaints_repository() -> AsyncGenerator[ComplaintsRepository, None]:
    async with get_connection() as conn:
        yield ComplaintsRepository(conn)


def get_cache_provider() -> CacheProvider:
    global _cache_provider
    if _cache_provider is None:
        _cache_provider = CacheProvider()
    return _cache_provider


def get_rate_limiter() -> RateLimiterProvider:
    global _rate_limiter
    if _rate_limiter is None:
        _rate_limiter = RateLimiterProvider()
    return _rate_limiter


def get_request_id(request: Request) -> str:
    request_id = request.headers.get("X-Request-ID")
    if not request_id:
        import uuid
        request_id = str(uuid.uuid4())
    return request_id


def get_triage_provider_dep():
    return get_triage_provider()


def get_statistics_service(
    repo: ComplaintsRepository = Depends(get_complaints_repository),
    cache: CacheProvider = Depends(get_cache_provider),
) -> StatisticsService:
    """Build the statistics service with its collaborators injected.

    Injected rather than constructed inside the handler, so a test can supply a
    stub repository or a cache without patching a module global, and so the
    service cannot reach for a dependency the caller did not agree to.
    """
    return StatisticsService(repo=repo, cache=cache)
