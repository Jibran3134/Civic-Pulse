import asyncio
import sys
from collections.abc import AsyncGenerator
from contextlib import asynccontextmanager

import psycopg
from psycopg.rows import dict_row
from psycopg_pool import AsyncConnectionPool

from app.core.config import get_settings
from app.core.logging import get_logger

logger = get_logger(__name__)
settings = get_settings()


def configure_event_loop_policy() -> None:
    """Make the running event loop compatible with psycopg's async driver.

    psycopg's async implementation cannot run on the Proactor loop that is
    Python's default on Windows; it needs the Selector loop. Setting a policy is
    process-global, so this must happen before any connection is created.

    Exposed as an explicit function rather than left as an import side effect
    because the Alembic environment needs it too and was not getting it:
    `alembic upgrade head` failed on a Windows developer machine with
    "Psycopg cannot use the 'ProactorEventLoop'" while working fine inside the
    Linux container. Two callers, one definition.
    """
    if sys.platform == "win32":
        asyncio.set_event_loop_policy(asyncio.WindowsSelectorEventLoopPolicy())


configure_event_loop_policy()

_pool: AsyncConnectionPool | None = None


async def create_pool() -> AsyncConnectionPool:
    global _pool
    if _pool is None:
        _pool = AsyncConnectionPool(
            settings.database_url,
            min_size=2,
            max_size=10,
            open=True,
            kwargs={"row_factory": dict_row, "autocommit": True},
        )
        await _pool.wait()
        logger.info("Database connection pool created")
    return _pool


async def close_pool() -> None:
    global _pool
    if _pool is not None:
        await _pool.close()
        _pool = None
        logger.info("Database connection pool closed")


@asynccontextmanager
async def get_connection() -> AsyncGenerator[psycopg.AsyncConnection, None]:
    pool = await create_pool()
    async with pool.connection() as conn:
        yield conn


async def health_check() -> bool:
        try:
            pool = await create_pool()
            async with pool.connection() as conn:
                await conn.execute("SELECT 1")
            return True
        except Exception:
            return False
