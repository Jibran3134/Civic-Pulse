import uuid
from typing import Any

import psycopg
from psycopg.rows import dict_row

from app.core.logging import get_logger

logger = get_logger(__name__)


class ComplaintsRepository:
    def __init__(self, conn: psycopg.AsyncConnection):
        self._conn = conn

    async def create(
        self,
        complaint_id: str,
        text: str,
        location: str,
        reporter_contact: str | None,
        category: str,
        priority: str,
        ai_summary: str | None,
        triaged_by: str,
        triage_latency_ms: int,
    ) -> dict[str, Any]:
        # The id is supplied by the caller rather than left to
        # gen_random_uuid(). The route needs the same value before triage so the
        # fallback WARNING can name the complaint it belongs to; a
        # server-generated id would only exist after the INSERT, which is after
        # triage has already run and already failed.
        query = """
            INSERT INTO complaints (id, text, location, reporter_contact, category, priority,
                                    ai_summary, triaged_by, triage_latency_ms, status)
            VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, 'open')
            RETURNING id, text, location, reporter_contact, category, priority, status,
                      ai_summary, triaged_by, triage_latency_ms, created_at, updated_at
        """
        async with self._conn.cursor(row_factory=dict_row) as cur:
            await cur.execute(
                query,
                (
                    complaint_id,
                    text,
                    location,
                    reporter_contact,
                    category,
                    priority,
                    ai_summary,
                    triaged_by,
                    triage_latency_ms,
                ),
            )
            row = await cur.fetchone()
            if row is None:
                # INSERT ... RETURNING always yields a row unless a BEFORE
                # trigger suppressed it. Failing loudly beats handing None to a
                # Pydantic model and getting a confusing 500.
                raise RuntimeError("complaints INSERT returned no row")
            return row

    async def get_by_id(self, complaint_id: uuid.UUID) -> dict[str, Any] | None:
        query = """
            SELECT id, text, location, reporter_contact, category, priority, status,
                   ai_summary, triaged_by, triage_latency_ms, created_at, updated_at
            FROM complaints
            WHERE id = %s
        """
        async with self._conn.cursor(row_factory=dict_row) as cur:
            await cur.execute(query, (str(complaint_id),))
            return await cur.fetchone()

    async def list_complaints(
        self,
        category: str | None = None,
        priority: str | None = None,
        status: str | None = None,
        page: int = 1,
        page_size: int = 20,
    ) -> tuple[list[dict[str, Any]], int]:
        """Filtered, paginated listing.

        Serves the dashboard's list query. `ix_complaints_status_priority`
        covers the (status, priority) filter combination and
        `ix_complaints_created_at` backs the created_at DESC ordering that
        pagination walks.

        The secondary sort key on id is not decoration: the seed inserts every
        row inside one transaction, so now() -- and therefore created_at -- is
        identical for all of them. Ordering by created_at alone leaves the order
        of equal keys undefined, so LIMIT/OFFSET can return rows in a different
        order on each execution: the same complaint appears on page 1 and again
        on page 2, and another is skipped entirely.
        """
        where_clauses: list[str] = []
        params: list[Any] = []

        if category:
            where_clauses.append("category = %s")
            params.append(category)
        if priority:
            where_clauses.append("priority = %s")
            params.append(priority)
        if status:
            where_clauses.append("status = %s")
            params.append(status)

        where_sql = "WHERE " + " AND ".join(where_clauses) if where_clauses else ""

        count_query = f"SELECT COUNT(*) as total FROM complaints {where_sql}"
        async with self._conn.cursor(row_factory=dict_row) as cur:
            await cur.execute(count_query, params)
            count_row = await cur.fetchone()
        # COUNT(*) always returns exactly one row, so the `or` branch is
        # unreachable; it just satisfies the Optional the driver reports.
        total = (count_row or {"total": 0})["total"]

        offset = (page - 1) * page_size
        list_query = f"""
            SELECT id, text, location, reporter_contact, category, priority, status,
                   ai_summary, triaged_by, triage_latency_ms, created_at, updated_at
            FROM complaints
            {where_sql}
            ORDER BY created_at DESC, id DESC
            LIMIT %s OFFSET %s
        """
        # LIMIT/OFFSET take real integers. The previous version passed
        # str(page_size)/str(offset) and relied on Postgres coercing them,
        # which also defeated index-friendly parameter typing.
        params.extend([page_size, offset])
        async with self._conn.cursor(row_factory=dict_row) as cur:
            await cur.execute(list_query, params)
            rows = await cur.fetchall()

        return rows, total

    async def update_status(
        self,
        complaint_id: uuid.UUID,
        new_status: str,
    ) -> dict[str, Any] | None:
        query = """
            UPDATE complaints
            SET status = %s, updated_at = NOW()
            WHERE id = %s
            RETURNING id, text, location, reporter_contact, category, priority, status,
                      ai_summary, triaged_by, triage_latency_ms, created_at, updated_at
        """
        async with self._conn.cursor(row_factory=dict_row) as cur:
            await cur.execute(query, (new_status, str(complaint_id)))
            return await cur.fetchone()

    async def get_stats(self) -> dict[str, Any]:
        query = """
            SELECT
                category,
                priority,
                COUNT(*) as count
            FROM complaints
            GROUP BY category, priority
        """
        async with self._conn.cursor(row_factory=dict_row) as cur:
            await cur.execute(query)
            rows = await cur.fetchall()

        by_category: dict[str, int] = {}
        by_priority: dict[str, int] = {}

        for row in rows:
            cat = row["category"]
            pri = row["priority"]
            cnt = row["count"]

            by_category[cat] = by_category.get(cat, 0) + cnt
            by_priority[pri] = by_priority.get(pri, 0) + cnt

        return {"by_category": by_category, "by_priority": by_priority}
