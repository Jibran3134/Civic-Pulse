"""Regression tests for the production-correctness fixes.

Each test here corresponds to a defect that was live in the merged tree and is
now fixed. They are written as regressions rather than as coverage: the point is
that re-introducing the bug makes a specific test fail with a message that says
what the bug was.

  * SIGTERM exit 137 -- the lifespan overwrote uvicorn's signal handlers
  * hollow /metrics   -- http_requests_total and the latency histogram were
                        declared but never incremented
  * 422 not 400       -- validation returned FastAPI's default array body
  * 500 not 400       -- untyped enum filters and PATCH status reached the DB
"""

import signal
import uuid

import pytest
from httpx import ASGITransport, AsyncClient

from app.core.metrics import REQUEST_COUNT, REQUEST_LATENCY
from app.main import app, lifespan

pytestmark = pytest.mark.integration


# --------------------------------------------------------------------- SIGTERM
class TestGracefulShutdown:
    async def test_lifespan_does_not_replace_uvicorn_signal_handlers(self, no_real_io):
        """The regression that produced `docker stop` exit 137.

        uvicorn installs its own SIGTERM/SIGINT handlers inside Server.serve(),
        and those are what stop the listener and drain in-flight requests. An
        earlier lifespan called signal.signal() and overwrote them with a
        handler that only set a module-level boolean nothing read, so the
        container logged "SIGTERM received" and then sat there until Docker's
        grace period expired and SIGKILL dropped live requests.
        """
        watched = (signal.SIGTERM, signal.SIGINT)
        before = {s: signal.getsignal(s) for s in watched}
        async with lifespan(app):
            pass
        after = {s: signal.getsignal(s) for s in watched}

        assert before == after, "the lifespan replaced a signal handler"

    async def test_teardown_runs_on_shutdown(self, no_real_io):
        async with lifespan(app):
            pass
        # These are the lines that stop the container holding sockets open
        # against Postgres and Redis across a rolling update.
        assert "close_pool" in no_real_io
        assert "close_redis" in no_real_io

    async def test_teardown_runs_even_if_startup_body_raises(self, no_real_io):
        # try/finally around the yield: a failure during startup must not leak
        # the pool for the life of the process.
        with pytest.raises(RuntimeError):
            async with lifespan(app):
                raise RuntimeError("boom")
        assert "close_pool" in no_real_io

    async def test_marks_app_as_shutting_down(self, no_real_io):
        async with lifespan(app):
            assert app.state.shutting_down is False
        assert app.state.shutting_down is True


@pytest.fixture
def no_real_io(monkeypatch):
    """Stub the pool and Redis so the lifespan runs without Docker."""
    calls: list[str] = []

    async def record(name):
        calls.append(name)

    async def fake_pool():
        await record("create_pool")
        return object()

    monkeypatch.setattr("app.main.create_pool", fake_pool)
    monkeypatch.setattr("app.main.close_pool", lambda: record("close_pool"))
    monkeypatch.setattr("app.main.close_redis_client", lambda: record("close_redis"))
    return calls


# --------------------------------------------------------------------- metrics
def _total(metric) -> float:
    """Sum a counter's samples via the public collect() API.

    Restricted to *_total: a Counter also exposes _created, whose value is a
    process-start timestamp rather than a count, and summing it makes every
    assertion meaningless.
    """
    value = 0.0
    for m in metric.collect():
        for s in m.samples:
            if s.name.endswith("_total"):
                value += s.value
    return value


def _observations(histogram) -> float:
    value = 0.0
    for m in histogram.collect():
        for s in m.samples:
            if s.name.endswith("_count"):
                value += s.value
    return value


class TestMetricsAreNotHollow:
    async def test_request_count_increments(self):
        before = _total(REQUEST_COUNT)
        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as ac:
            await ac.get("/health")
        # The series existed with # HELP/# TYPE headers and no samples, so
        # /metrics looked correct to anyone skimming it.
        assert _total(REQUEST_COUNT) == before + 1

    async def test_request_latency_is_observed(self):
        before = _observations(REQUEST_LATENCY)
        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as ac:
            await ac.get("/health")
        assert _observations(REQUEST_LATENCY) == before + 1

    async def test_status_code_is_recorded(self):
        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as ac:
            await ac.get("/health")
        statuses = {
            s.labels.get("status")
            for m in REQUEST_COUNT.collect()
            for s in m.samples
            if s.name.endswith("_total")
        }
        assert "200" in statuses

    async def test_labels_use_the_route_template_not_the_raw_path(self):
        """Cardinality guard.

        Labelling on request.url.path would create a distinct time series per
        complaint UUID, which is enough to take a Prometheus server down.
        """
        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as ac:
            await ac.get("/api/complaints/00000000-0000-0000-0000-000000000001")

        endpoints = {
            s.labels.get("endpoint")
            for m in REQUEST_COUNT.collect()
            for s in m.samples
            if s.name.endswith("_total")
        }
        assert any("{" in (e or "") for e in endpoints), "no templated route label found"
        assert not any("00000000-0000" in (e or "") for e in endpoints)

    async def test_metrics_endpoint_serves_the_four_contract_series(self):
        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as ac:
            body = (await ac.get("/metrics")).text
        for name in (
            "http_requests_total",
            "http_request_duration_seconds",
            "triage_duration_seconds",
            "triage_fallback_total",
        ):
            assert name in body, f"{name} missing from /metrics"

    async def test_triage_latency_moves_after_a_complaint(self, client, unique_complaint):
        from app.core.metrics import TRIAGE_LATENCY

        before = _observations(TRIAGE_LATENCY)
        await client.post("/api/complaints", json=unique_complaint)
        assert _observations(TRIAGE_LATENCY) == before + 1


# ------------------------------------------------------------------ validation
class TestValidationReturns400:
    """The contract asks for 400 plus a field-level body, not FastAPI's 422."""

    async def test_short_text_is_400_with_field_error(self, client):
        r = await client.post("/api/complaints", json={"text": "short", "location": "Mall Road"})
        assert r.status_code == 400
        assert "text" in r.json()["field_errors"]

    async def test_short_location_is_400(self, client):
        r = await client.post("/api/complaints", json={"text": "x" * 40, "location": "x"})
        assert r.status_code == 400
        assert "location" in r.json()["field_errors"]

    async def test_all_bad_fields_reported_at_once(self, client):
        # A form should be able to highlight every problem, not make the citizen
        # fix them one round trip at a time.
        body = (await client.post("/api/complaints", json={"text": "x", "location": "y"})).json()
        assert set(body["field_errors"]) == {"text", "location"}

    async def test_whitespace_only_text_is_rejected(self, client):
        # Length validation alone accepts 40 spaces.
        r = await client.post("/api/complaints", json={"text": " " * 40, "location": "Mall Road"})
        assert r.status_code == 400

    async def test_body_includes_request_id(self, client):
        r = await client.post("/api/complaints", json={"location": "Mall Road"})
        # So a user reporting a validation problem can be traced in the logs.
        assert r.json().get("request_id")

    async def test_malformed_uuid_is_400_not_500(self, client):
        assert (await client.get("/api/complaints/not-a-uuid")).status_code == 400

    async def test_out_of_range_pagination_is_400(self, client):
        for params in ({"page": 0}, {"page_size": 0}, {"page_size": 101}):
            assert (await client.get("/api/complaints", params=params)).status_code == 400


class TestEnumInputsAre400:
    """Regression: untyped str reached Postgres or raised ValueError -> 500."""

    @pytest.mark.parametrize("field", ["category", "priority", "status"])
    async def test_unknown_filter_value_is_400(self, client, field):
        r = await client.get("/api/complaints", params={field: "not_a_real_value"})
        assert r.status_code == 400, f"{field} produced {r.status_code}"

    async def test_unknown_status_in_patch_is_400(self, client, unique_complaint):
        created = (await client.post("/api/complaints", json=unique_complaint)).json()
        r = await client.patch(
            f"/api/complaints/{created['id']}/status", json={"status": "banana"}
        )
        # Previously Status("banana") raised ValueError inside the route and the
        # global handler turned it into a 500 -- a client error reported as a
        # server fault.
        assert r.status_code == 400
        assert "status" in r.json()["field_errors"]


# ------------------------------------------------------------------- 409 detail
class TestConflictDetail:
    async def test_409_names_both_ends_and_the_legal_moves(self, client, unique_complaint):
        created = (await client.post("/api/complaints", json=unique_complaint)).json()
        cid = created["id"]
        await client.patch(f"/api/complaints/{cid}/status", json={"status": "in_progress"})
        await client.patch(f"/api/complaints/{cid}/status", json={"status": "resolved"})

        detail = (
            await client.patch(f"/api/complaints/{cid}/status", json={"status": "open"})
        ).json()["detail"]

        # The frontend surfaces this verbatim, so it has to contain both ends of
        # the rejected move plus what would have been allowed.
        assert "resolved" in detail and "open" in detail
        assert "terminal" in detail.lower()

    async def test_409_lists_alternatives_for_a_non_terminal_state(self, client, unique_complaint):
        created = (await client.post("/api/complaints", json=unique_complaint)).json()
        cid = created["id"]
        detail = (
            await client.patch(f"/api/complaints/{cid}/status", json={"status": "resolved"})
        ).json()["detail"]
        assert "in_progress" in detail


# ----------------------------------------------------------------- rate limiter
class TestRateLimiterKeying:
    def test_prefers_the_forwarded_client_ip(self):
        from app.routes.complaints import client_ip_from

        class FakeRequest:
            def __init__(self, headers, host):
                self.headers = headers
                self.client = type("C", (), {"host": host})()

        # Behind the Ingress, request.client.host is the ingress controller's pod
        # IP. Keying on that puts every internet user in one shared bucket, so a
        # single caller can lock out everyone else.
        assert client_ip_from(FakeRequest({"x-forwarded-for": "203.0.113.7, 10.0.0.1"}, "10.0.0.5")) == "203.0.113.7"

    def test_falls_back_to_peer_ip(self):
        from app.routes.complaints import client_ip_from

        class FakeRequest:
            headers: dict = {}
            client = type("C", (), {"host": "198.51.100.9"})()

        assert client_ip_from(FakeRequest()) == "198.51.100.9"


# --------------------------------------------------------------------- OpenAPI
class TestOpenApiContract:
    def test_stats_documents_x_cache(self):
        # The frontend renders X-Cache and its typed client is generated from
        # this schema; an undeclared header is a header the client cannot see.
        responses = app.openapi()["paths"]["/api/stats"]["get"]["responses"]
        assert "X-Cache" in responses["200"].get("headers", {})

    def test_429_documents_retry_after(self):
        responses = app.openapi()["paths"]["/api/complaints"]["post"]["responses"]
        assert "Retry-After" in responses["429"].get("headers", {})

    def test_create_and_patch_document_400(self):
        paths = app.openapi()["paths"]
        assert "400" in paths["/api/complaints"]["post"]["responses"]
        assert "400" in paths["/api/complaints/{complaint_id}/status"]["patch"]["responses"]

    def test_health_routes_are_not_under_the_api_prefix(self):
        # Kubernetes probes hit /health and /ready at the root; the Ingress only
        # routes /api to the backend, so a prefixed probe would be unreachable.
        paths = set(app.openapi()["paths"])
        assert {"/health", "/ready"} <= paths
        assert "/api/health" not in paths


# ----------------------------------------------------------------- pagination
class TestPaginationIsStable:
    async def test_walking_pages_neither_repeats_nor_skips(self, client, unique_complaint):
        """Regression: ORDER BY created_at alone left equal keys unordered.

        The seed inserts every row in one transaction, so all of them share a
        created_at. LIMIT/OFFSET over a set of equal sort keys can therefore
        return rows in a different order each time -- the same complaint on
        page 1 and page 2, and another silently skipped.
        """
        for _ in range(3):
            await client.post("/api/complaints", json=unique_complaint)

        page_size = 2
        total = (await client.get("/api/complaints", params={"page_size": 100})).json()["total"]
        pages = -(-total // page_size)

        seen: list[str] = []
        for page in range(1, pages + 1):
            data = (
                await client.get("/api/complaints", params={"page": page, "page_size": page_size})
            ).json()
            seen.extend(item["id"] for item in data["items"])

        assert len(seen) == len(set(seen)), "a complaint appeared on two pages"
        assert len(seen) == total, "pagination skipped rows"

        past_end = (
            await client.get("/api/complaints", params={"page": pages + 1, "page_size": page_size})
        ).json()
        assert past_end["items"] == []


@pytest.fixture
def unique_complaint():
    """Unique payload so the triage content cache never serves a later test."""
    return {
        "text": f"Streetlight out on this lane for four nights, ref {uuid.uuid4().hex[:8]}",
        "location": "Model Town Block B, Lahore",
        "reporter_contact": None,
    }
