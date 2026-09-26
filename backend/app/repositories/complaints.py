import uuid
from datetime import datetime
from typing import Any, Optional

import psycopg
from psycopg.rows import dict_row

from app.core.logging import get_logger


logger = get_logger(__name__)


class ComplaintsRepository:
    def __init__(self, conn: psycopg.AsyncConnection):
        self._conn = conn

    async def create(
        self,
        text: str,
        location: str,
        reporter_contact: Optional[str],
        category: str,
        priority: str,
        ai_summary: Optional[str],
        triaged_by: str,
        triage_latency_ms: int,
    ) -> dict[str, Any]:
        query = """
            INSERT INTO complaints (text, location, reporter_contact, category, priority,
                                    ai_summary, triaged_by, triage_latency_ms, status)
            VALUES (%s, %s, %s, %s, %s, %s, %s, %s, 'open')
            RETURNING id, text, location, reporter_contact, category, priority, status,
                      ai_summary, triaged_by, triage_latency_ms, created_at, updated_at
        """
        async with self._conn.cursor(row_factory=dict_row) as cur:
            await cur.execute(
                query,
                (
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
            return row

    async def get_by_id(self, complaint_id: uuid.UUID) -> Optional[dict[str, Any]]:
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
        category: Optional[str] = None,
        priority: Optional[str] = None,
        status: Optional[str] = None,
        page: int = 1,
        page_size: int = 20,
    ) -> tuple[list[dict[str, Any]], int]:
        where_clauses = []
        params = []

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
            total = (await cur.fetchone())["total"]

        offset = (page - 1) * page_size
        list_query = f"""
            SELECT id, text, location, reporter_contact, category, priority, status,
                   ai_summary, triaged_by, triage_latency_ms, created_at, updated_at
            FROM complaints
            {where_sql}
            ORDER BY created_at DESC
            LIMIT %s OFFSET %s
        """
        params.extend([page_size, offset])
        async with self._conn.cursor(row_factory=dict_row) as cur:
            await cur.execute(list_query, params)
            rows = await cur.fetchall()

        return rows, total

    async def update_status(
        self,
        complaint_id: uuid.UUID,
        new_status: str,
    ) -> Optional[dict[str, Any]]:
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

        by_category = {}
        by_priority = {}

        for row in rows:
            cat = row["category"]
            pri = row["priority"]
            cnt = row["count"]

            by_category[cat] = by_category.get(cat, 0) + cnt
            by_priority[pri] = by_priority.get(pri, 0) + cnt

        return {"by_category": by_category, "by_priority": by_priority}