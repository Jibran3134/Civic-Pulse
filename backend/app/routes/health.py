from fastapi import APIRouter, Response
from fastapi.responses import Response as FastAPIResponse
from prometheus_client import CONTENT_TYPE_LATEST, Counter, Histogram, generate_latest
from pydantic import BaseModel

from app.core.database import health_check as db_health_check
from app.core.logging import get_logger
from app.providers.cache import get_redis_client

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


async def _redis_health_check() -> bool:
    """Perform a fresh Redis ping to verify connectivity."""
    try:
        client = await get_redis_client()
        await client.ping()
        return True
    except Exception:
        return False


@router.get("/ready", response_model=ReadyResponse, tags=["health"])
async def ready(response: Response):
    """Readiness probe - 200 only if Postgres and Redis are reachable."""
    db_ok = await db_health_check()
    redis_ok = await _redis_health_check()

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
