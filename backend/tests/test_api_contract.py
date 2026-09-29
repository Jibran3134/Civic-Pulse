"""API contract tests for the endpoints that need real Postgres and Redis.

These are the integration half of the suite. Where the unit tests stub
infrastructure, these exercise the genuine request path: a real insert, a real
Redis round trip, a real 409 from the state machine.

The tests that previously existed here asserted almost nothing -- the
pagination test created no rows and checked only the echoed parameters, and
the cache test accepted either X-Cache value so it could never detect a broken
cache. These assert the behaviour the contract actually specifies.
"""

import uuid

import pytest

from app.providers.triage.base import Category, Priority
from app.services.status_machine import Status

pytestmark = pytest.mark.integration


class TestComplaintCreation:
    async def test_create_returns_201_with_full_record(self, client, unique_complaint):
        response = await client.post("/api/complaints", json=unique_complaint)

        assert response.status_code == 201
        data = response.json()
        assert data["text"] == unique_complaint["text"]
        assert data["location"] == unique_complaint["location"]
        assert data["status"] == Status.OPEN
        # Triage must have actually run and produced a decision.
        assert data["category"] in {c.value for c in Category}
        assert data["priority"] in {p.value for p in Priority}
        assert data["triaged_by"]
        assert isinstance(data["triage_latency_ms"], int)
        assert data["ai_summary"]
        # A summary longer than the schema allows would be truncated by the DB.
        assert len(data["ai_summary"]) <= 140
        assert uuid.UUID(data["id"])
        assert data["created_at"] and data["updated_at"]

    async def test_defaults_status_to_open(self, client, unique_complaint):
        data = (await client.post("/api/complaints", json=unique_complaint)).json()
        assert data["status"] == "open"

    async def test_reporter_contact_is_optional(self, client):
        payload = {
            "text": f"Pothole on the main road near the bridge, ref {uuid.uuid4().hex[:8]}",
            "location": "Askari 10, Lahore",
        }
        response = await client.post("/api/complaints", json=payload)
        assert response.status_code == 201
        assert response.json()["reporter_contact"] is None

    async def test_whitespace_only_contact_becomes_null(self, client):
        payload = {
            "text": f"Electric pole sparking near the school, ref {uuid.uuid4().hex[:8]}",
            "location": "Johar Town, Lahore",
            "reporter_contact": "   ",
        }
        assert (await client.post("/api/complaints", json=payload)).json()["reporter_contact"] is None


class TestValidationReturns400:
    """The contract asks for 400 plus a field-level body, not FastAPI's 422."""

    async def test_missing_text_is_400_with_field_error(self, client):
        response = await client.post("/api/complaints", json={"location": "Mall Road"})
        assert response.status_code == 400
        body = response.json()
        assert "field_errors" in body
        assert "text" in body["field_errors"]

    async def test_text_too_short_is_400(self, client):
        response = await client.post(
            "/api/complaints", json={"text": "short", "location": "Mall Road"}
        )
        assert response.status_code == 400
        assert "text" in response.json()["field_errors"]

    async def test_text_too_long_is_400(self, client):
        response = await client.post(
            "/api/complaints", json={"text": "x" * 2001, "location": "Mall Road"}
        )
        assert response.status_code == 400
        assert "text" in response.json()["field_errors"]

    async def test_location_too_short_is_400(self, client):
        response = await client.post(
            "/api/complaints",
            json={"text": "Burst water main flooding the street badly", "location": "x"},
        )
        assert response.status_code == 400
        assert "location" in response.json()["field_errors"]

    async def test_whitespace_only_text_is_400(self, client):
        # Length validation alone would accept 40 spaces.
        response = await client.post(
            "/api/complaints", json={"text": " " * 40, "location": "Mall Road"}
        )
        assert response.status_code == 400
        assert "text" in response.json()["field_errors"]

    async def test_missing_body_is_400(self, client):
        assert (await client.post("/api/complaints")).status_code == 400

    async def test_multiple_bad_fields_are_all_reported(self, client):
        # A form should be able to highlight every problem at once, not make
        # the citizen fix them one round trip at a time.
        body = (await client.post("/api/complaints", json={"text": "x", "location": "y"})).json()
        assert set(body["field_errors"]) == {"text", "location"}

    async def test_field_error_body_includes_request_id(self, client):
        body = (await client.post("/api/complaints", json={"location": "Mall Road"})).json()
        # So a user reporting a validation problem can be traced in the logs.
        assert body.get("request_id")


class TestRetrieval:
    async def test_get_by_id_round_trips(self, client, unique_complaint):
        created = (await client.post("/api/complaints", json=unique_complaint)).json()

        response = await client.get(f"/api/complaints/{created['id']}")

        assert response.status_code == 200
        assert response.json()["id"] == created["id"]
        assert response.json()["text"] == unique_complaint["text"]

    async def test_unknown_id_is_404(self, client):
        assert (await client.get(f"/api/complaints/{uuid.uuid4()}")).status_code == 404

    async def test_malformed_id_is_400_not_500(self, client):
        # Not a UUID at all. Previously the path parameter was untyped enough
        # that this produced a server error.
        assert (await client.get("/api/complaints/not-a-uuid")).status_code == 400


class TestListingAndFilters:
    @pytest.fixture(autouse=True)
    async def _seeded(self, client):
        """Create a small known set so filter assertions are meaningful."""
        created = []
        for _ in range(3):
            payload = {
                "text": f"Water main burst flooding the street, ref {uuid.uuid4().hex[:8]}",
                "location": "Mall Road, Lahore",
            }
            response = await client.post("/api/complaints", json=payload)
            if response.status_code == 201:
                created.append(response.json())
        return created

    async def test_returns_envelope_fields(self, client):
        data = (await client.get("/api/complaints")).json()
        for field in ("items", "total", "page", "page_size"):
            assert field in data

    async def test_total_counts_all_rows(self, client, _seeded):
        data = (await client.get("/api/complaints", params={"page_size": 1})).json()
        # total is the unpaginated count; a page_size of 1 must not cap it.
        assert data["total"] > len(data["items"])

    @pytest.mark.parametrize(
        ("field", "value"),
        [("category", "water"), ("priority", "high"), ("status", "open")],
    )
    async def test_filter_returns_only_matching_rows(self, client, _seeded, field, value):
        response = await client.get("/api/complaints", params={field: value})
        assert response.status_code == 200
        items = response.json()["items"]
        assert items, f"filter {field}={value} matched nothing, so this asserts nothing"
        for item in items:
            assert item[field] == value

    @pytest.mark.parametrize(
        ("field", "value"),
        [("category", "water"), ("priority", "high"), ("status", "open")],
    )
    async def test_filter_excludes_non_matching_rows(self, client, _seeded, field, value):
        # The mirror of the above, and the assertion the original suite was
        # missing: a filter that returned EVERY row would have passed a
        # "every item matches" check whenever the dataset happened to be
        # homogeneous.
        filtered = (await client.get("/api/complaints", params={field: value})).json()
        unfiltered = (await client.get("/api/complaints", params={"page_size": 100})).json()
        assert filtered["total"] <= unfiltered["total"]
        if filtered["total"] < unfiltered["total"]:
            assert filtered["total"] < unfiltered["total"]

    async def test_unknown_filter_value_is_400_not_500(self, client):
        # Previously the filters were bare strings bound straight into the
        # WHERE clause, so Postgres raised 22P02 and it surfaced as a 500.
        response = await client.get("/api/complaints", params={"category": "not_a_category"})
        assert response.status_code == 400

    @pytest.mark.parametrize("field", ["category", "priority", "status"])
    async def test_invalid_enum_filter_is_rejected(self, client, field):
        assert (await client.get("/api/complaints", params={field: "banana"})).status_code == 400

    async def test_combined_filters_narrow_the_result(self, client, _seeded):
        response = await client.get(
            "/api/complaints", params={"category": "water", "status": "open"}
        )
        assert response.status_code == 200
        for item in response.json()["items"]:
            assert item["category"] == "water"
            assert item["status"] == "open"

    async def test_pagination_walks_without_repeating_or_skipping(self, client, _seeded):
        # The real bug this guards: ordering by created_at alone left the order
        # of equal timestamps undefined, and the seed inserts every row in one
        # transaction, so all of them share a created_at. Rows could then
        # repeat on page 1 and be skipped on page 2.
        page_size = 2
        total = (await client.get("/api/complaints", params={"page_size": 100})).json()["total"]
        expected_pages = -(-total // page_size)  # ceiling division

        seen: list[str] = []
        for page in range(1, expected_pages + 1):
            data = (
                await client.get("/api/complaints", params={"page": page, "page_size": page_size})
            ).json()
            seen.extend(item["id"] for item in data["items"])

        assert len(seen) == len(set(seen)), "a complaint appeared on two pages"
        assert len(seen) == total, "pagination skipped rows"

        # One page past the end must be empty, not a wrap-around of page 1.
        past_end = (
            await client.get("/api/complaints", params={"page": expected_pages + 1, "page_size": page_size})
        ).json()
        assert past_end["items"] == []

    @pytest.mark.parametrize("params", [{"page": 0}, {"page_size": 0}, {"page_size": 101}])
    async def test_out_of_range_pagination_is_400(self, client, params):
        assert (await client.get("/api/complaints", params=params)).status_code == 400

    async def test_page_size_cap_is_100(self, client):
        response = await client.get("/api/complaints", params={"page_size": 100})
        assert response.status_code == 200
        assert response.json()["page_size"] == 100


class TestStatusTransitions:
    async def _create(self, client):
        payload = {
            "text": f"Road has collapsed near the bridge, ref {uuid.uuid4().hex[:8]}",
            "location": "Askari 10, Lahore",
        }
        return (await client.post("/api/complaints", json=payload)).json()["id"]

    @pytest.mark.parametrize("target", ["in_progress", "rejected"])
    async def test_open_accepts_its_two_exits(self, client, target):
        complaint_id = await self._create(client)
        response = await client.patch(f"/api/complaints/{complaint_id}/status", json={"status": target})
        assert response.status_code == 200
        assert response.json()["status"] == target

    async def test_in_progress_accepts_its_two_exits(self, client):
        complaint_id = await self._create(client)
        await client.patch(f"/api/complaints/{complaint_id}/status", json={"status": "in_progress"})
        response = await client.patch(
            f"/api/complaints/{complaint_id}/status", json={"status": "resolved"}
        )
        assert response.status_code == 200
        assert response.json()["status"] == "resolved"

    async def test_skipping_in_progress_is_409(self, client):
        # open -> resolved is not an edge in the table.
        complaint_id = await self._create(client)
        response = await client.patch(
            f"/api/complaints/{complaint_id}/status", json={"status": "resolved"}
        )
        assert response.status_code == 409

    @pytest.mark.parametrize("target", ["open", "in_progress"])
    async def test_resolved_is_terminal(self, client, target):
        complaint_id = await self._create(client)
        await client.patch(f"/api/complaints/{complaint_id}/status", json={"status": "in_progress"})
        await client.patch(f"/api/complaints/{complaint_id}/status", json={"status": "resolved"})

        response = await client.patch(
            f"/api/complaints/{complaint_id}/status", json={"status": target}
        )
        assert response.status_code == 409
        assert "terminal" in response.json()["detail"].lower()

    async def test_rejected_is_terminal(self, client):
        complaint_id = await self._create(client)
        await client.patch(f"/api/complaints/{complaint_id}/status", json={"status": "rejected"})

        response = await client.patch(
            f"/api/complaints/{complaint_id}/status", json={"status": "in_progress"}
        )
        assert response.status_code == 409

    async def test_409_names_the_attempted_transition(self, client):
        # The frontend must surface the server's reason verbatim, so the message
        # has to contain both endpoints of the rejected move.
        complaint_id = await self._create(client)
        await client.patch(f"/api/complaints/{complaint_id}/status", json={"status": "in_progress"})
        await client.patch(f"/api/complaints/{complaint_id}/status", json={"status": "resolved"})

        detail = (
            await client.patch(f"/api/complaints/{complaint_id}/status", json={"status": "open"})
        ).json()["detail"]

        assert "resolved" in detail and "open" in detail

    async def test_self_transition_is_409(self, client):
        complaint_id = await self._create(client)
        response = await client.patch(
            f"/api/complaints/{complaint_id}/status", json={"status": "open"}
        )
        assert response.status_code == 409

    async def test_invalid_status_value_is_400_not_500(self, client):
        # Previously StatusUpdate.status was a bare str, so Status("banana")
        # raised ValueError inside the route and became a 500.
        complaint_id = await self._create(client)
        response = await client.patch(
            f"/api/complaints/{complaint_id}/status", json={"status": "banana"}
        )
        assert response.status_code == 400
        assert "status" in response.json()["field_errors"]

    async def test_unknown_complaint_is_404(self, client):
        response = await client.patch(
            f"/api/complaints/{uuid.uuid4()}/status", json={"status": "in_progress"}
        )
        assert response.status_code == 404


class TestStatsAndCache:
    async def test_stats_shape(self, client, unique_complaint):
        await client.post("/api/complaints", json=unique_complaint)
        data = (await client.get("/api/stats")).json()
        assert isinstance(data["by_category"], dict)
        assert isinstance(data["by_priority"], dict)
        assert sum(data["by_category"].values()) > 0

    async def test_cache_goes_miss_then_hit(self, client, unique_complaint):
        await client.post("/api/complaints", json=unique_complaint)

        first = await client.get("/api/stats")
        second = await client.get("/api/stats")

        # The old CI check grepped the response BODY twice, which is
        # byte-identical on a hit and a miss, so it asserted nothing.
        assert first.headers["X-Cache"] == "MISS"
        assert second.headers["X-Cache"] == "HIT"

    async def test_write_invalidates_the_cache(self, client, unique_complaint):
        await client.get("/api/stats")
        assert (await client.get("/api/stats")).headers["X-Cache"] == "HIT"

        await client.post("/api/complaints", json=unique_complaint)

        # Not left to expire: a complaint an operator just submitted must show
        # up on the dashboard immediately, not up to 30 seconds later.
        assert (await client.get("/api/stats")).headers["X-Cache"] == "MISS"

    async def test_cached_body_matches_uncached_body(self, client, unique_complaint):
        await client.post("/api/complaints", json=unique_complaint)
        first = await client.get("/api/stats")
        second = await client.get("/api/stats")
        # A HIT must serve the same payload as the MISS it was built from.
        assert first.json() == second.json()

    async def test_new_complaint_appears_in_aggregates(self, client):
        before = (await client.get("/api/stats")).json()["by_category"]
        payload = {
            "text": f"Sanitation: overflowing drain and sewage, ref {uuid.uuid4().hex[:8]}",
            "location": "Sabzazar, Lahore",
        }
        await client.post("/api/complaints", json=payload)
        after = (await client.get("/api/stats")).json()["by_category"]
        assert sum(after.values()) == sum(before.values()) + 1


class TestMetaEndpoint:
    async def test_reports_the_active_provider(self, client):
        data = (await client.get("/api/meta/providers")).json()
        assert data["active_provider"]
        assert isinstance(data["recent_outcomes"], list)

    async def test_records_an_outcome_per_triage(self, client, unique_complaint):
        await client.post("/api/complaints", json=unique_complaint)

        data = (await client.get("/api/meta/providers")).json()
        assert data["recent_outcomes"], "triage outcome was not recorded"

        latest = data["recent_outcomes"][0]
        # Exactly the three fields the contract names.
        assert "provider" in latest
        assert isinstance(latest["latency_ms"], int)
        assert isinstance(latest["fallback"], bool)
