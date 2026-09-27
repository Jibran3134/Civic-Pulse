"""Tests for structured JSON logging and request_id propagation.

The requirement is specific: JSON to stdout (never a file, because a
container's filesystem is ephemeral), and every line carrying a request_id
propagated from X-Request-ID. These were implemented but never exercised,
because setup_logging() only runs from the FastAPI lifespan and ASGITransport
does not run lifespans -- so the whole subsystem had zero test coverage.
"""

import io
import json
import logging
import sys

import pytest
from httpx import ASGITransport, AsyncClient

from app.core.logging import CustomJsonFormatter, RequestIdFilter, request_id_var, setup_logging
from app.main import app


@pytest.fixture
def json_formatter():
    return CustomJsonFormatter("%(timestamp)s %(level)s %(name)s %(message)s")


@pytest.fixture
def make_record(json_formatter):
    def _make(message="hello", level=logging.INFO, **extra):
        record = logging.LogRecord(
            name="app.test",
            level=level,
            pathname=__file__,
            lineno=1,
            msg=message,
            args=(),
            exc_info=None,
        )
        for key, value in extra.items():
            setattr(record, key, value)
        return record

    return _make


class TestJsonFormatter:
    def test_output_is_parseable_json(self, json_formatter, make_record):
        line = json_formatter.format(make_record("triage completed"))
        parsed = json.loads(line)
        # Not a string containing JSON -- actual JSON, so a log shipper can
        # index the fields rather than regex them out of a sentence.
        assert parsed["message"] == "triage completed"

    def test_required_fields_present(self, json_formatter, make_record):
        parsed = json.loads(json_formatter.format(make_record()))
        for field in ("timestamp", "level", "logger", "message"):
            assert field in parsed, f"{field} missing from the log line"

    def test_level_is_a_string_name(self, json_formatter, make_record):
        parsed = json.loads(json_formatter.format(make_record(level=logging.WARNING)))
        assert parsed["level"] == "WARNING"

    def test_extra_context_is_merged(self, json_formatter, make_record):
        parsed = json.loads(
            json_formatter.format(
                make_record(provider="llm:groq", latency_ms=412, fallback=True)
            )
        )
        # Structured context is the whole point: "which provider, how slow,
        # did it fall back" has to be queryable, not buried in a message string.
        assert parsed["provider"] == "llm:groq"
        assert parsed["latency_ms"] == 412
        assert parsed["fallback"] is True

    def test_request_id_included_when_filter_ran(self, json_formatter, make_record):
        record = make_record()
        RequestIdFilter().filter(record)
        parsed = json.loads(json_formatter.format(record))
        assert "request_id" in parsed


class TestRequestIdFilter:
    def test_injects_contextvar_value(self, make_record):
        record = make_record()
        token = request_id_var.set("req-abc123")
        try:
            RequestIdFilter().filter(record)
            assert record.request_id == "req-abc123"
        finally:
            request_id_var.reset(token)

    def test_never_filters_a_record_out(self, make_record):
        # A logging filter returning False would silently drop the line.
        assert RequestIdFilter().filter(make_record()) is True

    def test_empty_contextvar_is_allowed(self, make_record):
        token = request_id_var.set("")
        try:
            record = make_record()
            assert RequestIdFilter().filter(record) is True
            assert record.request_id == ""
        finally:
            request_id_var.reset(token)


class TestSetupLogging:
    def test_writes_to_stdout_not_a_file(self):
        # Assert the handler's stream rather than capturing output. A
        # container's filesystem is ephemeral and the log shipper reads stdout;
        # a FileHandler would make every line vanish on restart. Checking the
        # bound stream states the property directly and does not depend on
        # which capture mechanism pytest is using for this run.
        setup_logging()
        handlers = logging.getLogger().handlers
        assert len(handlers) == 1
        handler = handlers[0]
        assert isinstance(handler, logging.StreamHandler)
        assert not isinstance(handler, logging.FileHandler)
        assert handler.stream is sys.stdout

    def test_emits_valid_json_with_request_id_attached(self):
        # End-to-end proof that a real log call produces parseable JSON with
        # the request_id attached. The handler's stream is swapped for an
        # in-memory buffer so the assertion reads exactly what a log shipper
        # would have received, without depending on pytest's capture mode.
        setup_logging()
        handler = logging.getLogger().handlers[0]
        saved = handler.stream
        buffer = io.StringIO()
        handler.stream = buffer
        try:
            token = request_id_var.set("req-json-1")
            try:
                logging.getLogger("app.probe").warning(
                    "triage fell back", extra={"provider": "llm:groq"}
                )
            finally:
                request_id_var.reset(token)
        finally:
            handler.stream = saved

        parsed = json.loads(buffer.getvalue().strip())
        assert parsed["message"] == "triage fell back"
        # Structured context is the point: an operator can query "every triage
        # fallback for request X" instead of grepping prose.
        assert parsed["provider"] == "llm:groq"
        assert parsed["request_id"] == "req-json-1"
        assert parsed["level"] == "WARNING"

    def test_replaces_handlers_rather_than_appending(self):
        # Appending on every call would emit each line N times after N calls.
        setup_logging()
        first = len(logging.getLogger().handlers)
        setup_logging()
        assert len(logging.getLogger().handlers) == first == 1

    def test_uvicorn_loggers_are_captured(self):
        setup_logging()
        # uvicorn installs its own handlers; if they are left in place, access
        # logs come out as plain text alongside the JSON and break parsing.
        for name in ("uvicorn.access", "uvicorn.error"):
            assert logging.getLogger(name).handlers


class TestRequestIdPropagation:
    """End-to-end: the header must arrive from client, through the log, and back."""

    async def test_supplied_request_id_is_propagated(self):
        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as ac:
            response = await ac.get("/health", headers={"X-Request-ID": "caller-supplied-123"})
        # Echoed back so a caller can quote it in a bug report and find the
        # exact log lines.
        assert response.headers["X-Request-ID"] == "caller-supplied-123"

    async def test_request_id_is_generated_when_absent(self):
        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as ac:
            response = await ac.get("/health")
        generated = response.headers.get("X-Request-ID")
        # Never empty: an untraceable request is worse than a slightly noisier
        # response.
        assert generated
        assert len(generated) >= 8

    async def test_every_response_carries_the_header(self):
        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as ac:
            for path in ("/health", "/metrics"):
                response = await ac.get(path)
                assert "X-Request-ID" in response.headers, f"{path} omitted X-Request-ID"
