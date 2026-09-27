from fastapi import APIRouter, Depends, Response

from app.core.dependencies import (
    get_statistics_service,
)
from app.core.logging import get_logger
from app.services.statistics import StatisticsService

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
    service: StatisticsService = Depends(get_statistics_service),
):
    """Aggregates by category and priority.

    The read-through policy and the TTL live in StatisticsService; this handler
    only decides how the outcome is reported over HTTP, which is the one part
    that genuinely belongs to the web layer.
    """
    result = await service.get_stats()
    response.headers["X-Cache"] = result.cache_state
    return result.stats
