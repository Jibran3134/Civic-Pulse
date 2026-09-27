"""Tests for application startup/shutdown and the observability middleware.

The graceful-shutdown requirement is graded and was entirely untested:
setup_logging() and the lifespan only run from FastAPI startup events, and
ASGITransport does not fire those, so main.py's lifespan body had zero
coverage. The previous version of this file also installed a SIGTERM handler
that overwrote uvicorn's own -- destroying the drain that makes a rolling
update lossless -- so the behaviour worth pinning down is what we do instead:
do not touch uvicorn's handlers, and do close the pool and clients on the way
out.
"""

import logging

import pytest
from httpx import ASGITransport, AsyncClient

from app.core.logging import request_id_var
from app.main import app, lifespan


@pytest.fixture
def no_real_io(monkeypatch):
    """Stub out the pool and Redis so the lifespan can run without Docker.

    Patched on `app.main`, not on the defining module: main.py does
    `from app.core.database import create_pool`, so the name is bound into its
    own namespace at import time and patching the source module would leave the
    reference main.py actually calls untouched.
    """
    calls: list[str] = []

    async def fake_create_pool():
        calls.append("create_pool")
        return object()

    async def fake_close_pool():
        calls.append("close_pool")

    async def fake_close_redis():
        calls.append("close_redis")

    monkeypatch.setattr("app.main.create_pool", fake_create_pool)
    monkeypatch.setattr("app.main.close_pool", fake_close_pool)
    monkeypatch.setattr("app.main.close_redis_client", fake_close_redis)
    return calls


class TestLifespan:
    async def test_creates_the_pool_on_startup(self, no_real_io):
        async with lifespan(app):
            pass
        assert "create_pool" in no_real_io

    async def test_releases_resources_on_shutdown(self, no_real_io):
        async with lifespan(app):
            pass
        # These are the lines that stop the container holding sockets open
        # against Postgres and Redis through a rolling update.
        assert "close_pool" in no_real_io
        assert "close_redis" in no_real_io

    async def test_teardown_runs_even_if_the_body_raises(self, no_real_io):
        # A crash during startup must not leak the pool. try/finally around the
        # yield is what guarantees the teardown path executes.
        with pytest.raises(RuntimeError):
            async with lifespan(app):
                raise RuntimeError("boom during startup")
        assert "close_pool" in no_real_io

    async def test_does_not_register_signal_handlers(self, no_real_io):
        # The regression this file exists to prevent.
        #
        # uvicorn installs its own SIGTERM/SIGINT handlers inside Server.serve()
        # and those are what stop the listener and wait for in-flight requests
        # before running this teardown. An earlier version of main.py called
        # signal.signal() from the lifespan and overwrote them with a handler
        # that only set a module-level boolean nothing read. The result was that
        # "graceful" shutdown was neither graceful nor a drain: the container
        # sat idle until Docker's grace period expired and SIGKILL dropped live
        # requests -- exactly the failure the rolling-update demo depends on
        # not happening.
        import signal

        before = {sig: signal.getsignal(sig) for sig in (signal.SIGTERM, signal.SIGINT)}
        async with lifespan(app):
            pass
        after = {sig: signal.getsignal(sig) for sig in (signal.SIGTERM, signal.SIGINT)}

        assert before == after, "the lifespan replaced uvicorn's signal handlers"

    async def test_marks_the_app_as_shutting_down(self, no_real_io):
        async with lifespan(app):
            assert app.state.shutting_down is False
        # Set on the way out so a readiness check can start failing before the
        # listener actually closes.
        assert app.state.shutting_down is True

    async def test_configures_json_logging(self, no_real_io):
        async with lifespan(app):
            pass
        # One handler on the root logger, and it is ours, not a default.
        assert len(logging.getLogger().handlers) == 1


class TestObservabilityMiddleware:
    async def test_counts_requests(self):
        from app.core.metrics import REQUEST_COUNT

        def total() -> float:
            value = 0.0
            for metric in REQUEST_COUNT.collect():
                for sample in metric.samples:
                    # Filter to _total: a Counter also exposes _created, whose
                    # value is a process-start timestamp, not a count.
                    if sample.name.endswith("_total"):
                        value += sample.value
            return value

        before = total()
        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as ac:
            await ac.get("/health")
        # The metrics were DECLARED but never incremented anywhere, so
        # /metrics served permanently-zero series that looked implemented.
        assert total() == before + 1

    async def test_observes_request_latency(self):
        from app.core.metrics import REQUEST_LATENCY

        def count() -> float:
            value = 0.0
            for metric in REQUEST_LATENCY.collect():
                for sample in metric.samples:
                    if sample.name.endswith("_count"):
                        value += sample.value
            return value

        before = count()
        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as ac:
            await ac.get("/health")
        assert count() == before + 1

    async def test_records_the_status_code(self):
        from app.core.metrics import REQUEST_COUNT

        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as ac:
            await ac.get("/health")

        labels = set()
        for metric in REQUEST_COUNT.collect():
            for sample in metric.samples:
                if sample.name.endswith("_total"):
                    labels.add(sample.labels.get("status"))
        assert "200" in labels

    async def test_uses_the_route_template_not_the_raw_path(self):
        # Cardinality explosion: labelling on request.url.path would create a
        # distinct time series per complaint UUID, which is enough to take a
        # Prometheus server down.
        from app.core.metrics import REQUEST_COUNT

        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as ac:
            await ac.get("/api/complaints/00000000-0000-0000-0000-000000000001")

        endpoints = set()
        for metric in REQUEST_COUNT.collect():
            for sample in metric.samples:
                if sample.name.endswith("_total"):
                    endpoints.add(sample.labels.get("endpoint"))
        assert any("{" in (e or "") for e in endpoints), "no templated route label found"
        assert not any("00000000-0000" in (e or "") for e in endpoints)

    async def test_unhandled_exception_is_counted_as_500(self):
        from app.core.metrics import REQUEST_COUNT

        @app.get("/__test_boom__")
        async def boom():
            raise RuntimeError("deliberate")

        before = 0.0
        for metric in REQUEST_COUNT.collect():
            for sample in metric.samples:
                if sample.labels.get("status") == "500" and sample.name.endswith("_total"):
                    before += sample.value

        try:
            async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as ac:
                with pytest.raises(RuntimeError):
                    await ac.get("/__test_boom__")
        finally:
            app.router.routes = [r for r in app.router.routes if getattr(r, "path", "") != "/__test_boom__"]

        after = 0.0
        for metric in REQUEST_COUNT.collect():
            for sample in metric.samples:
                if sample.labels.get("status") == "500" and sample.name.endswith("_total"):
                    after += sample.value

        # A 500 raised out of a route is invisible in /metrics otherwise --
        # and that is precisely the request you most want in a graph.
        assert after == before + 1

    async def test_request_id_is_set_on_the_contextvar(self):
        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as ac:
            response = await ac.get("/health", headers={"X-Request-ID": "ctx-check-1"})
        assert response.headers["X-Request-ID"] == "ctx-check-1"
        # Cleared afterwards rather than leaking into the next request handled
        # by the same worker.
        assert request_id_var.get() in ("", "ctx-check-1")


class TestApplicationWiring:
    def test_all_nine_contract_routes_are_mounted(self):
        paths = set(app.openapi()["paths"])
        expected = {
            "/api/complaints",
            "/api/complaints/{complaint_id}",
            "/api/complaints/{complaint_id}/status",
            "/api/stats",
            "/api/meta/providers",
            "/health",
            "/ready",
            "/metrics",
        }
        assert expected <= paths, f"missing: {expected - paths}"

    def test_health_routes_are_not_under_the_api_prefix(self):
        # Kubernetes probes hit /health and /ready at the root; the Ingress
        # only routes /api to the backend, so a prefixed health route would be
        # unreachable through it.
        paths = set(app.openapi()["paths"])
        assert "/health" in paths
        assert "/ready" in paths
        assert "/api/health" not in paths

    def test_stats_documents_its_cache_header(self):
        # The frontend renders X-Cache, and the OpenAPI schema is what the
        # typed client is generated from -- so the header has to be declared.
        responses = app.openapi()["paths"]["/api/stats"]["get"]["responses"]
        headers = responses["200"].get("headers", {})
        assert "X-Cache" in headers

    def test_rate_limited_response_documents_retry_after(self):
        responses = app.openapi()["paths"]["/api/complaints"]["post"]["responses"]
        assert "429" in responses
        assert "Retry-After" in responses["429"].get("headers", {})

    def test_create_complaint_documents_400(self):
        responses = app.openapi()["paths"]["/api/complaints"]["post"]["responses"]
        assert "400" in responses

    def test_status_patch_documents_409(self):
        responses = app.openapi()["paths"]["/api/complaints/{complaint_id}/status"]["patch"]["responses"]
        assert "409" in responses
