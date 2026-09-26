from fastapi import APIRouter, Depends, Response
from pydantic import BaseModel
from prometheus_client import Counter, Histogram, generate_latest, CONTENT_TYPE_LATEST
from fastapi.responses import Response as FastAPIResponse

from app.core.database import health_check as db_health_check
from app.providers.cache import CacheProvider
from app.core.dependencies import get_cache_provider
from app.core.logging import get_logger


logger = get_logger(__name__)

router = APIRouter()

# Prometheus metrics
REQUEST_COUNT = Counter("http_requests_total", "Total HTTP requests", ["method", "endpoint", "status"])
REQUEST_LATENCY = Histogram("http_request_duration_seconds", "HTTP request latency", ["method", "endpoint"])
TRIAGE_LATENCY = Histogram("triage_duration_seconds", "Triage latency")
FALLBACK_COUNTER = Counter("triage_fallback_total", "Total triage fallbacks")


class HealthResponse(BaseModel):
    status: str = "ok"


class ReadyResponse(BaseModel):
    status: str
    database: str
    redis: str


@router.get("/health", response_model=HealthResponse, tags=["health"])
async def health():
    """Liveness probe - process is alive, does not touch database."""
    return HealthResponse()


@router.get("/ready", response_model=ReadyResponse, tags=["health"])
async def ready(
    response: Response,
    cache: CacheProvider = Depends(get_cache_provider),
):
    """Readiness probe - 200 only if Postgres and Redis are reachable."""
    db_ok = await db_health_check()
    redis_ok = await cache.health_check()

    if not db_ok or not redis_ok:
        response.status_code = 503
        return ReadyResponse(
            status="not ready",
            database="ok" if db_ok else "failed",
            redis="ok" if redis_ok else "failed",
        )

    return ReadyResponse(status="ready", database="ok", redis="ok")


@router.get("/metrics", tags=["metrics"])
async def metrics():
    """Prometheus metrics endpoint."""
    return FastAPIResponse(content=generate_latest(), media_type=CONTENT_TYPE_LATEST)