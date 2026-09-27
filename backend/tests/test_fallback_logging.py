"""The fallback WARNING must name the complaint it belongs to.

Section 2.2 requires "one WARNING per triage fallback with the complaint id,
the provider and the error class". The service accepted a complaint_id argument
but the route never passed one, so the id in that log was the literal string
"pre-persist" on every single fallback in production -- the one field an
operator needs to look up the complaint was never the one that is useful.

The id is now minted in the route before triage and threaded into the log.
"""

import logging
from unittest.mock import AsyncMock, patch
from uuid import uuid4

import pytest

from app.providers.triage.llm_groq import LLMTriage
from app.services.triage import TriageService


class TestFallbackWarningCarriesComplaintId:
    # The triage pipeline checks the 24h content-hash cache before it calls a
    # provider, so a fixed complaint text is served from Redis and the provider
    # is never invoked -- the fallback branch does not run and no WARNING is
    # emitted. Each test therefore uses text unique to its own run, or it would
    # silently pass or fail depending on what a previous test left in Redis.
    @pytest.mark.asyncio
    async def test_warning_names_the_complaint_when_one_is_supplied(self, caplog):
        """The contract: provider, error class and complaint id all present."""
        service = TriageService(provider=LLMTriage(api_key="test-key"))
        complaint_id = str(uuid4())
        text = f"Water main burst unique to this run {uuid4()}"

        with (
            caplog.at_level(logging.WARNING),
            patch("httpx.AsyncClient.post", new_callable=AsyncMock) as mock_post,
        ):
            mock_post.side_effect = RuntimeError("provider exploded")
            result = await service.triage(text, "Lahore", complaint_id=complaint_id)

        # The fallback still happened, and the user still gets an answer.
        assert result.triaged_by == "rules:fallback"
        assert result.category.value in {"water", "other"}

        warnings = [r for r in caplog.records if r.getMessage().startswith("triage_fallback")]
        assert warnings, "no triage_fallback WARNING was emitted"
        record = warnings[0]
        assert record.complaint_id == complaint_id
        assert record.provider == "llm:groq"
        assert record.error_class == "RuntimeError"

    @pytest.mark.asyncio
    async def test_warning_says_pre_persist_only_when_truly_pre_persist(self, caplog):
        """The sentinel must mean what it says, and only that.

        If every fallback reports "pre-persist" the field is decoration. This
        pins that the string is reserved for the genuinely-unknown case.
        """
        service = TriageService(provider=LLMTriage(api_key="test-key"))
        text = f"Water main burst unique to this run {uuid4()}"

        with (
            caplog.at_level(logging.WARNING),
            patch("httpx.AsyncClient.post", new_callable=AsyncMock) as mock_post,
        ):
            mock_post.side_effect = RuntimeError("provider exploded")
            await service.triage(text, "Lahore")

        warnings = [r for r in caplog.records if r.getMessage().startswith("triage_fallback")]
        assert warnings
        assert warnings[0].complaint_id == "pre-persist"

    @pytest.mark.asyncio
    async def test_a_cache_hit_short_circuits_before_the_provider(self, caplog):
        """Documents the interaction that made the two tests above necessary.

        The content-hash cache is checked first, so a repeat submission is
        answered from Redis without any provider call. Worth pinning: it is the
        reason a fixed test string cannot be used to exercise the fallback path.
        """
        service = TriageService(provider=LLMTriage(api_key="test-key"))
        text = f"Repeated complaint unique to this run {uuid4()}"

        with patch("httpx.AsyncClient.post", new_callable=AsyncMock) as mock_post:
            mock_post.side_effect = RuntimeError("provider exploded")
            first = await service.triage(text, "Lahore", complaint_id=str(uuid4()))
            assert mock_post.call_count == 1

        with caplog.at_level(logging.WARNING), patch(
            "httpx.AsyncClient.post", new_callable=AsyncMock
        ) as second_post:
            second = await service.triage(text, "Lahore", complaint_id=str(uuid4()))
            assert second_post.call_count == 0, "a cache hit must not call the provider"

        assert first.triaged_by == "rules:fallback"
        assert second.category == first.category


class TestComplaintIdIsPersistedNotRegenerated:
    @pytest.mark.asyncio
    async def test_created_id_is_the_one_passed_to_triage(self, client, unique_complaint):
        """The id the route mints must be the id that reaches the database.

        If these diverged, the log would point at a complaint that does not
        exist -- which is worse than logging nothing, because it looks
        actionable.
        """
        seen: list[str] = []
        original = TriageService.triage

        async def spy(self, text, location, complaint_id=None):
            seen.append(complaint_id)
            return await original(self, text, location, complaint_id=complaint_id)

        with patch.object(TriageService, "triage", spy):
            created = (await client.post("/api/complaints", json=unique_complaint)).json()

        assert seen, "triage was called without a complaint id"
        assert seen[0] is not None
        assert seen[0] == created["id"], (
            "the id passed to triage does not match the persisted row"
        )

    @pytest.mark.asyncio
    async def test_persisted_id_is_a_valid_uuid(self, client, unique_complaint):
        from uuid import UUID

        created = (await client.post("/api/complaints", json=unique_complaint)).json()
        UUID(created["id"])  # raises if not a UUID

    @pytest.mark.asyncio
    async def test_two_complaints_get_distinct_ids(self, client):
        ids = set()
        for i in range(3):
            payload = {
                "text": f"Distinct water complaint number {i} on the same street",
                "location": "Mall Road",
            }
            body = (await client.post("/api/complaints", json=payload)).json()
            ids.add(body["id"])

        assert len(ids) == 3, "ids are not unique across inserts"
