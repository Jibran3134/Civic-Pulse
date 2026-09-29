import time
from collections.abc import AsyncGenerator
from contextlib import asynccontextmanager

from fastapi import FastAPI, Request
from fastapi.exceptions import RequestValidationError
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse

from app.core.config import get_settings
from app.core.database import close_pool, create_pool
from app.core.dependencies import get_request_id
from app.core.logging import get_logger, request_id_var, setup_logging
from app.core.metrics import REQUEST_COUNT, REQUEST_LATENCY
from app.providers.cache import close_redis_client
from app.routes import complaints, health, meta, stats

settings = get_settings()
logger = get_logger(__name__)


@asynccontextmanager
async def lifespan(app: FastAPI) -> AsyncGenerator[None, None]:
    setup_logging()
    logger.info(
        "Starting CivicPulse backend",
        extra={"environment": settings.environment, "triage_provider": settings.triage_provider},
    )

    await create_pool()

    # NOTE on SIGTERM. uvicorn installs its own SIGTERM/SIGINT handlers inside
    # Server.serve(), and those are what stop the listener, wait for in-flight
    # requests to finish, and only then run this teardown.
    #
    # This function used to call signal.signal() from the lifespan, replacing
    # them with a handler that set a module-level boolean nothing ever read.
    # The effect was the opposite of graceful: the container logged "SIGTERM
    # received", set the flag, and then sat there until Docker's grace period
    # expired and SIGKILL arrived. Measured on this image, `docker stop -t 25`
    # exited 137 with no "Waiting for application shutdown" and no pool close
    # -- in-flight requests were dropped, which is the exact failure the
    # zero-downtime rollout demo and the rollback runbook depend on avoiding.
    #
    # So no signal handler is registered here. The ordering Kubernetes needs is
    # handled where it belongs: backend.yaml's preStop sleep removes the pod
    # from Service endpoints before SIGTERM is delivered, and
    # terminationGracePeriodSeconds bounds the drain.

    app.state.shutting_down = False

    try:
        yield
    finally:
        # Uvicorn has already drained in-flight requests by the time this runs,
        # so these connections are genuinely idle. Closing them is what stops
        # the container holding sockets open against Postgres across a rolling
        # update. try/finally so a failure during startup still releases the
        # pool rather than leaking it for the life of the process.
        logger.info("Shutting down CivicPulse backend")
        app.state.shutting_down = True
        await close_pool()
        await close_redis_client()


app = FastAPI(
    title="CivicPulse API",
    version="0.1.0",
    lifespan=lifespan,
    docs_url="/docs" if not settings.is_production else None,
    redoc_url="/redoc" if not settings.is_production else None,
    # The interactive docs are hidden in production, but the raw schema was
    # still served -- an unauthenticated, complete inventory of every route and
    # field on a public deployment. It goes with them.
    openapi_url=None if settings.is_production else "/openapi.json",
)

# allow_origins=["*"] together with allow_credentials=True is inert: browsers
# reject `Access-Control-Allow-Origin: *` whenever credentials are included, so
# the pair silently does nothing. The production topology is same-origin (nginx
# serves the frontend and proxies /api), so the correct default is to allow no
# cross-origin access at all; a deployment that genuinely needs a separate
# origin sets CORS_ORIGINS.
app.add_middleware(
    CORSMiddleware,
    allow_origins=settings.cors_origins,
    allow_credentials=False,
    allow_methods=["GET", "POST", "PATCH", "OPTIONS"],
    allow_headers=["Content-Type", "X-Request-ID"],
    # The frontend renders X-Cache, and it needs to read it cross-document.
    expose_headers=["X-Request-ID", "X-Cache", "Retry-After"],
)


def _route_template(request: Request) -> str:
    """The matched route path, for metric labels.

    Labelling on request.url.path would create one time series per complaint
    UUID, which is enough cardinality to take a Prometheus server down. The
    route template is a fixed, bounded set of strings.
    """
    route = request.scope.get("route")
    return getattr(route, "path", None) or "unmatched"


@app.middleware("http")
async def observability_middleware(request: Request, call_next):
    """Attach a request_id, time the request, and record Prometheus metrics.

    One middleware does all three so request_id propagation and metric
    collection cannot drift apart: any request that is logged is by
    construction the same request that was counted.
    """
    request_id = get_request_id(request)
    request_id_var.set(request_id)
    request.state.request_id = request_id

    logger.info(
        "Request started",
        extra={
            "method": request.method,
            "path": request.url.path,
            "client": request.client.host if request.client else None,
        },
    )

    started = time.perf_counter()
    try:
        response = await call_next(request)
    except Exception:
        # Count the failure before it propagates, otherwise a 500 raised out of
        # a route never appears in /metrics -- and that is exactly the request
        # you most want in a graph.
        endpoint = _route_template(request)
        REQUEST_COUNT.labels(request.method, endpoint, "500").inc()
        REQUEST_LATENCY.labels(request.method, endpoint).observe(time.perf_counter() - started)
        raise

    elapsed = time.perf_counter() - started
    # Resolved AFTER call_next. Middleware wraps the router, so scope["route"]
    # is only populated once the router has matched; reading it on the way in
    # yields "unmatched" for every request.
    endpoint = _route_template(request)
    REQUEST_COUNT.labels(request.method, endpoint, str(response.status_code)).inc()
    REQUEST_LATENCY.labels(request.method, endpoint).observe(elapsed)

    response.headers["X-Request-ID"] = request_id

    logger.info(
        "Request completed",
        extra={
            "endpoint": endpoint,
            "status_code": response.status_code,
            "duration_ms": round(elapsed * 1000, 2),
        },
    )
    return response


@app.exception_handler(RequestValidationError)
async def validation_exception_handler(request: Request, exc: RequestValidationError):
    """Return 400 with a field-level error body.

    The API contract asks for 400 plus a field-level body on POST
    /api/complaints. FastAPI's default is 422 with a `detail: [...]` array,
    which does not match the declared ErrorResponse schema and is not what the
    frontend's typed client is generated against. Pydantic's list is collapsed
    into {field: message} so one field yields one entry and a form can render
    it directly.
    """
    field_errors: dict[str, str] = {}
    for error in exc.errors():
        location = [str(p) for p in error.get("loc", ()) if p not in ("body", "query", "path")]
        field = ".".join(location) if location else "body"
        # Keep the first message per field: one bad input usually trips several
        # validators and a form has room to show only one.
        field_errors.setdefault(field, error.get("msg", "invalid value"))

    logger.info("Validation error", extra={"fields": sorted(field_errors)})

    return JSONResponse(
        status_code=400,
        content={
            "detail": "Validation failed",
            "field_errors": field_errors,
            "request_id": getattr(request.state, "request_id", ""),
        },
    )


@app.exception_handler(Exception)
async def global_exception_handler(request: Request, exc: Exception):
    logger.exception("Unhandled exception", extra={"path": request.url.path})
    return JSONResponse(
        status_code=500,
        content={"detail": "Internal server error"},
    )


app.include_router(health.router, tags=["health"])
app.include_router(complaints.router, prefix="/api", tags=["complaints"])
app.include_router(stats.router, prefix="/api", tags=["stats"])
app.include_router(meta.router, prefix="/api", tags=["meta"])
