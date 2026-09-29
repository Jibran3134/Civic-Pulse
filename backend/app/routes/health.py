from fastapi import APIRouter, Response
from fastapi.responses import Response as PrometheusResponse
from prometheus_client import CONTENT_TYPE_LATEST, generate_latest
from pydantic import BaseModel

from app.core.database import health_check as db_health_check
from app.core.logging import get_logger
from app.providers.cache import redis_health_check

logger = get_logger(__name__)

router = APIRouter()

# The counters themselves live in app/core/metrics.py. Declaring them here and
# in the middleware would either duplicate the series (Prometheus rejects a
# second registration of the same name) or leave one half uninitialised. The
# middleware in main.py increments them; this module only serves the scrape.


class HealthResponse(BaseModel):
    status: str = "ok"


class ReadyResponse(BaseModel):
    status: str
    database: str
    redis: str


@router.get("/health", response_model=HealthResponse, tags=["health"])
async def health():
    """Liveness probe.

    Deliberately touches nothing but the process itself. Kubernetes restarts
    the pod when this fails, so making it depend on Postgres would turn a slow
    database into a restart loop across the whole deployment.
    """
    return HealthResponse()


@router.get("/ready", response_model=ReadyResponse, tags=["health"])
async def ready(response: Response):
    """Readiness probe.

    Readiness is the opposite decision: a failure here removes the pod from the
    Service endpoints so no new traffic arrives, but does NOT restart the pod.
    So this one must check the dependencies the pod actually needs to serve a
    request -- Postgres and Redis -- and name whichever failed.
    """
    db_ok = await db_health_check()
    redis_ok = await redis_health_check()

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
    """Prometheus scrape endpoint (the Grafana dashboard bonus builds on this)."""
    return PrometheusResponse(content=generate_latest(), media_type=CONTENT_TYPE_LATEST)
