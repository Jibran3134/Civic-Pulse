"""
Tests for OllamaTriage (backend/app/providers/triage/ollama.py).

All HTTP calls are mocked via httpx.MockTransport – no live Ollama server
required.  The tests cover:

  - happy path (valid JSON body)
  - markdown code-fence stripping
  - confidence clamped to [0, 1]
  - summary truncated at 140 chars
  - invalid Category value rejected (pydantic ValueError)
  - timeout retried once, then falls back to RuleBasedTriage via TriageService
  - 429 retried once, then falls back
  - 5xx retried once, then falls back
  - 400 NOT retried (raises immediately)
  - malformed JSON falls back (not a 500)
"""

import json
from unittest.mock import AsyncMock, MagicMock, patch

import httpx
import pytest

from app.providers.triage.base import Category, Priority
from app.providers.triage.ollama import OllamaTriage
from app.services.triage import TriageService

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

class InMemoryCache:
    """Minimal cache stub so TriageService can run without Redis."""

    def __init__(self):
        self.store: dict = {}
        self.counters: dict = {}
        self.lists: dict = {}

    async def get(self, key):
        return self.store.get(key), key in self.store

    async def set(self, key, value, ttl=30):
        self.store[key] = value

    async def incr(self, key):
        self.counters[key] = self.counters.get(key, 0) + 1
        return self.counters[key]

    async def lpush(self, key, value, max_len=20):
        self.lists.setdefault(key, []).insert(0, value)
        if max_len > 0:
            self.lists[key] = self.lists[key][:max_len]

    async def lrange(self, key, start=0, stop=-1):
        lst = self.lists.get(key, [])
        return lst[start:] if stop == -1 else lst[start : stop + 1]


def _make_ollama(base_url: str = "http://ollama-test:11434", max_retries: int = 1) -> OllamaTriage:
    """Return an OllamaTriage with settings overridden for fast tests."""
    provider = OllamaTriage(base_url=base_url, model="llama3.2:1b", timeout=5.0)
    # Override private retry attributes that would normally come from settings
    provider._max_retries = max_retries
    provider._retry_base_delay = 0.0  # zero delay so tests don't actually sleep
    return provider


def _success_response(payload: dict) -> httpx.Response:
    """Build a fake 200 httpx.Response wrapping a valid Ollama body."""
    body = json.dumps({"response": json.dumps(payload)})
    return httpx.Response(200, content=body.encode(), headers={"content-type": "application/json"})


def _error_response(status: int) -> httpx.Response:
    return httpx.Response(status, content=b"error", headers={"content-type": "text/plain"})


# ---------------------------------------------------------------------------
# Happy path
# ---------------------------------------------------------------------------

class TestOllamaHappyPath:
    @pytest.mark.asyncio
    async def test_happy_path_returns_triage_result(self):
        provider = _make_ollama()
        payload = {
            "category": "water",
            "priority": "high",
            "summary": "Burst pipe on Main Boulevard",
            "confidence": 0.95,
        }

        transport = httpx.MockTransport(
            lambda _req: _success_response(payload)
        )
        with patch("httpx.AsyncClient", return_value=httpx.AsyncClient(transport=transport)):
            result = await provider.triage("Water main burst", "Lahore")

        assert result.category == Category.WATER
        assert result.priority == Priority.HIGH
        assert result.summary == "Burst pipe on Main Boulevard"
        assert result.confidence == pytest.approx(0.95)
        assert provider.name == "llm:ollama"

    @pytest.mark.asyncio
    async def test_code_fence_stripping(self):
        provider = _make_ollama()
        inner = json.dumps({
            "category": "roads",
            "priority": "normal",
            "summary": "Pothole on Link Road",
            "confidence": 0.80,
        })
        fenced = f"```json\n{inner}\n```"
        body = json.dumps({"response": fenced})

        transport = httpx.MockTransport(
            lambda _req: httpx.Response(
                200, content=body.encode(), headers={"content-type": "application/json"}
            )
        )
        with patch("httpx.AsyncClient", return_value=httpx.AsyncClient(transport=transport)):
            result = await provider.triage("Pothole", "Lahore")

        assert result.category == Category.ROADS

    @pytest.mark.asyncio
    async def test_confidence_clamped_below_zero(self):
        provider = _make_ollama()
        payload = {
            "category": "sanitation",
            "priority": "low",
            "summary": "Open manhole",
            "confidence": -0.5,
        }
        transport = httpx.MockTransport(lambda _req: _success_response(payload))
        with patch("httpx.AsyncClient", return_value=httpx.AsyncClient(transport=transport)):
            result = await provider.triage("Open manhole", "Lahore")
        assert result.confidence == pytest.approx(0.0)

    @pytest.mark.asyncio
    async def test_confidence_clamped_above_one(self):
        provider = _make_ollama()
        payload = {
            "category": "electricity",
            "priority": "high",
            "summary": "Exposed wire",
            "confidence": 1.8,
        }
        transport = httpx.MockTransport(lambda _req: _success_response(payload))
        with patch("httpx.AsyncClient", return_value=httpx.AsyncClient(transport=transport)):
            result = await provider.triage("Live wire", "Lahore")
        assert result.confidence == pytest.approx(1.0)

    @pytest.mark.asyncio
    async def test_summary_truncated_over_140_chars(self):
        provider = _make_ollama()
        long_summary = "x" * 200
        payload = {
            "category": "other",
            "priority": "low",
            "summary": long_summary,
            "confidence": 0.5,
        }
        transport = httpx.MockTransport(lambda _req: _success_response(payload))
        with patch("httpx.AsyncClient", return_value=httpx.AsyncClient(transport=transport)):
            result = await provider.triage("Something", "Lahore")
        assert len(result.summary) == 140
        assert result.summary.endswith("...")

    @pytest.mark.asyncio
    async def test_invalid_category_raises_value_error(self):
        provider = _make_ollama()
        payload = {
            "category": "alien_invasion",
            "priority": "high",
            "summary": "Unusual activity",
            "confidence": 0.9,
        }
        transport = httpx.MockTransport(lambda _req: _success_response(payload))
        with (
            patch("httpx.AsyncClient", return_value=httpx.AsyncClient(transport=transport)),
            pytest.raises(ValueError),
        ):
            await provider.triage("Strange event", "Lahore")


# ---------------------------------------------------------------------------
# Retry behaviour
# ---------------------------------------------------------------------------

class TestOllamaRetry:
    """Each retryable error is retried once; the test confirms call count == 2."""

    @pytest.mark.asyncio
    async def test_timeout_retried_once_then_fallback(self):
        """Timeout → retry → timeout again → TriageService falls back to rules."""
        provider = _make_ollama(max_retries=1)
        cache = InMemoryCache()
        service = TriageService(provider=provider, cache=cache)

        call_count = 0

        async def mock_execute(_client, _text, _location):
            nonlocal call_count
            call_count += 1
            raise httpx.TimeoutException("timed out")

        with (
            patch.object(provider, "_execute_call", side_effect=mock_execute),
            patch("asyncio.sleep", new_callable=AsyncMock),
        ):
            result = await service.triage("Water main burst on road", "Lahore")

        assert call_count == 2  # initial + 1 retry
        assert result.triaged_by == "rules:fallback"

    @pytest.mark.asyncio
    async def test_429_retried_once_then_fallback(self):
        provider = _make_ollama(max_retries=1)
        cache = InMemoryCache()
        service = TriageService(provider=provider, cache=cache)

        mock_resp = MagicMock()
        mock_resp.status_code = 429

        call_count = 0

        async def mock_execute(_client, _text, _location):
            nonlocal call_count
            call_count += 1
            raise httpx.HTTPStatusError("429", request=MagicMock(), response=mock_resp)

        with (
            patch.object(provider, "_execute_call", side_effect=mock_execute),
            patch("asyncio.sleep", new_callable=AsyncMock),
        ):
            result = await service.triage("Electric outage near park", "Lahore")

        assert call_count == 2
        assert result.triaged_by == "rules:fallback"

    @pytest.mark.asyncio
    async def test_5xx_retried_once_then_fallback(self):
        provider = _make_ollama(max_retries=1)
        cache = InMemoryCache()
        service = TriageService(provider=provider, cache=cache)

        mock_resp = MagicMock()
        mock_resp.status_code = 503

        call_count = 0

        async def mock_execute(_client, _text, _location):
            nonlocal call_count
            call_count += 1
            raise httpx.HTTPStatusError("503", request=MagicMock(), response=mock_resp)

        with (
            patch.object(provider, "_execute_call", side_effect=mock_execute),
            patch("asyncio.sleep", new_callable=AsyncMock),
        ):
            result = await service.triage("Sewer blocked on street", "Lahore")

        assert call_count == 2
        assert result.triaged_by == "rules:fallback"

    @pytest.mark.asyncio
    async def test_400_not_retried(self):
        """A 400 is a non-retryable client error; only 1 call should be made."""
        provider = _make_ollama(max_retries=1)

        mock_resp = MagicMock()
        mock_resp.status_code = 400
        mock_resp.text = "Bad Request"

        call_count = 0

        async def mock_execute(_client, _text, _location):
            nonlocal call_count
            call_count += 1
            # Simulate the 400 guard in _execute_call
            raise httpx.HTTPStatusError("400", request=MagicMock(), response=mock_resp)

        with (
            patch.object(provider, "_execute_call", side_effect=mock_execute),
            pytest.raises(httpx.HTTPStatusError),
        ):
            await provider.triage("Test complaint", "Lahore")

        assert call_count == 1  # no retry

    @pytest.mark.asyncio
    async def test_malformed_json_falls_back_not_500(self):
        """If the model returns un-parseable JSON, TriageService falls back to rules."""
        provider = _make_ollama(max_retries=1)
        cache = InMemoryCache()
        service = TriageService(provider=provider, cache=cache)

        bad_body = json.dumps({"response": "this is prose, not JSON {"})

        transport = httpx.MockTransport(
            lambda _req: httpx.Response(
                200, content=bad_body.encode(), headers={"content-type": "application/json"}
            )
        )
        with patch("httpx.AsyncClient", return_value=httpx.AsyncClient(transport=transport)):
            result = await service.triage("Garbage pile on street", "Lahore")

        # json.JSONDecodeError propagates as ValueError → rules fallback
        assert result.triaged_by == "rules:fallback"
