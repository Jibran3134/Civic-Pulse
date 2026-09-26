import signal
import sys
from contextlib import asynccontextmanager
from typing import AsyncGenerator

from fastapi import FastAPI, Request, Response
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse

from app.core.config import get_settings
from app.core.logging import setup_logging, get_logger, request_id_var
from app.core.database import create_pool, close_pool, health_check as db_health_check
from app.core.dependencies import get_request_id
from app.routes import complaints, health, stats, meta

settings = get_settings()
logger = get_logger(__name__)

_shutdown = False


@asynccontextmanager
async def lifespan(app: FastAPI) -> AsyncGenerator[None, None]:
    setup_logging()
    logger.info("Starting CivicPulse backend", extra={"environment": settings.environment})

    await create_pool()

    def handle_sigterm(*args):
        global _shutdown
        logger.info("SIGTERM received, starting graceful shutdown")
        _shutdown = True

    signal.signal(signal.SIGTERM, handle_sigterm)
    signal.signal(signal.SIGINT, handle_sigterm)

    yield

    logger.info("Shutting down CivicPulse backend")
    await close_pool()


app = FastAPI(
    title="CivicPulse API",
    version="0.1.0",
    lifespan=lifespan,
    docs_url="/docs" if not settings.is_production else None,
    redoc_url="/redoc" if not settings.is_production else None,
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


@app.middleware("http")
async def request_id_middleware(request: Request, call_next):
    request_id = get_request_id(request)
    request_id_var.set(request_id)

    logger.info(
        "Request started",
        extra={
            "method": request.method,
            "path": request.url.path,
            "client": request.client.host if request.client else None,
        },
    )

    response = await call_next(request)
    response.headers["X-Request-ID"] = request_id

    logger.info(
        "Request completed",
        extra={"status_code": response.status_code},
    )
    return response


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


@app.get("/openapi.json", include_in_schema=False)
async def openapi_spec():
    return app.openapi()