from uuid import uuid4

import pytest
from httpx import ASGITransport, AsyncClient

from app.main import app


@pytest.fixture
async def client():
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as ac:
        yield ac


@pytest.fixture
def sample_complaint():
    return {
        "text": "Water main burst on Mall Road since fajr, water entering ground floors",
        "location": "Mall Road, Lahore",
        "reporter_contact": "0300-1234567",
    }


class TestComplaintsAPI:
    @pytest.mark.asyncio
    async def test_create_complaint(self, client, sample_complaint):
        response = await client.post("/api/complaints", json=sample_complaint)
        assert response.status_code == 201
        data = response.json()
        assert data["text"] == sample_complaint["text"]
        assert data["location"] == sample_complaint["location"]
        assert data["reporter_contact"] == sample_complaint["reporter_contact"]
        assert "category" in data
        assert "priority" in data
        assert "status" in data
        assert data["status"] == "open"
        assert "ai_summary" in data
        assert "triaged_by" in data
        assert "triage_latency_ms" in data
        assert "id" in data
        assert "created_at" in data

    @pytest.mark.asyncio
    async def test_get_complaint(self, client, sample_complaint):
        create_resp = await client.post("/api/complaints", json=sample_complaint)
        assert create_resp.status_code == 201
        complaint_id = create_resp.json()["id"]

        response = await client.get(f"/api/complaints/{complaint_id}")
        assert response.status_code == 200
        data = response.json()
        assert data["id"] == complaint_id
        assert data["text"] == sample_complaint["text"]

    @pytest.mark.asyncio
    async def test_get_nonexistent_complaint(self, client):
        response = await client.get(f"/api/complaints/{uuid4()}")
        assert response.status_code == 404

    @pytest.mark.asyncio
    async def test_list_complaints(self, client, sample_complaint):
        await client.post("/api/complaints", json=sample_complaint)
        response = await client.get("/api/complaints")
        assert response.status_code == 200
        data = response.json()
        assert "items" in data
        assert "total" in data
        assert "page" in data
        assert "page_size" in data
        assert data["total"] >= 1
        assert len(data["items"]) >= 1

    @pytest.mark.asyncio
    async def test_filter_complaints_by_category(self, client, sample_complaint):
        await client.post("/api/complaints", json=sample_complaint)
        response = await client.get("/api/complaints", params={"category": "water"})
        assert response.status_code == 200
        data = response.json()
        for item in data["items"]:
            assert item["category"] == "water"

    @pytest.mark.asyncio
    async def test_filter_complaints_by_priority(self, client, sample_complaint):
        await client.post("/api/complaints", json=sample_complaint)
        response = await client.get("/api/complaints", params={"priority": "high"})
        assert response.status_code == 200
        data = response.json()
        for item in data["items"]:
            assert item["priority"] == "high"

    @pytest.mark.asyncio
    async def test_filter_complaints_by_status(self, client, sample_complaint):
        await client.post("/api/complaints", json=sample_complaint)
        response = await client.get("/api/complaints", params={"status": "open"})
        assert response.status_code == 200
        data = response.json()
        for item in data["items"]:
            assert item["status"] == "open"

    @pytest.mark.asyncio
    async def test_pagination(self, client, sample_complaint):
        response = await client.get("/api/complaints", params={"page": 1, "page_size": 5})
        assert response.status_code == 200
        data = response.json()
        assert data["page"] == 1
        assert data["page_size"] == 5


class TestComplaintStatusTransitions:
    @pytest.mark.asyncio
    async def test_valid_transition_open_to_in_progress(self, client, sample_complaint):
        create_resp = await client.post("/api/complaints", json=sample_complaint)
        complaint_id = create_resp.json()["id"]

        response = await client.patch(
            f"/api/complaints/{complaint_id}/status",
            json={"status": "in_progress"}
        )
        assert response.status_code == 200
        assert response.json()["status"] == "in_progress"

    @pytest.mark.asyncio
    async def test_valid_transition_open_to_rejected(self, client, sample_complaint):
        create_resp = await client.post("/api/complaints", json=sample_complaint)
        complaint_id = create_resp.json()["id"]

        response = await client.patch(
            f"/api/complaints/{create_resp.json()['id']}/status",
            json={"status": "rejected"}
        )
        assert response.status_code == 200
        assert response.json()["status"] == "rejected"

    @pytest.mark.asyncio
    async def test_valid_transition_in_progress_to_resolved(self, client, sample_complaint):
        create_resp = await client.post("/api/complaints", json=sample_complaint)
        complaint_id = create_resp.json()["id"]

        await client.patch(
            f"/api/complaints/{complaint_id}/status",
            json={"status": "in_progress"}
        )

        response = await client.patch(
            f"/api/complaints/{complaint_id}/status",
            json={"status": "resolved"}
        )
        assert response.status_code == 200
        assert response.json()["status"] == "resolved"

    @pytest.mark.asyncio
    async def test_invalid_transition_resolved_to_open(self, client, sample_complaint):
        create_resp = await client.post("/api/complaints", json=sample_complaint)
        complaint_id = create_resp.json()["id"]

        await client.patch(
            f"/api/complaints/{complaint_id}/status",
            json={"status": "in_progress"}
        )
        await client.patch(
            f"/api/complaints/{complaint_id}/status",
            json={"status": "resolved"}
        )

        response = await client.patch(
            f"/api/complaints/{complaint_id}/status",
            json={"status": "open"}
        )
        assert response.status_code == 409
        assert "Invalid status transition" in response.json()["detail"]


class TestStatsEndpoint:
    @pytest.mark.asyncio
    async def test_stats_endpoint(self, client, sample_complaint):
        await client.post("/api/complaints", json=sample_complaint)
        response = await client.get("/api/stats")
        assert response.status_code == 200
        data = response.json()
        assert "by_category" in data
        assert "by_priority" in data
        assert isinstance(data["by_category"], dict)
        assert isinstance(data["by_priority"], dict)

    @pytest.mark.asyncio
    async def test_stats_cache_header(self, client, sample_complaint):
        await client.post("/api/complaints", json=sample_complaint)
        response = await client.get("/api/stats")
        assert "X-Cache" in response.headers
        assert response.headers["X-Cache"] in ["HIT", "MISS"]


class TestHealthEndpoints:
    @pytest.mark.asyncio
    async def test_health_endpoint(self, client):
        response = await client.get("/health")
        assert response.status_code == 200
        assert response.json() == {"status": "ok"}

    @pytest.mark.asyncio
    async def test_ready_endpoint(self, client):
        response = await client.get("/ready")
        assert response.status_code == 200
        data = response.json()
        assert data["status"] == "ready"
        assert data["database"] == "ok"
        assert data["redis"] == "ok"

    @pytest.mark.asyncio
    async def test_metrics_endpoint(self, client):
        response = await client.get("/metrics")
        assert response.status_code == 200
        assert "http_requests_total" in response.text
        assert "http_request_duration_seconds" in response.text


class TestMetaEndpoint:
    @pytest.mark.asyncio
    async def test_meta_providers_endpoint(self, client):
        response = await client.get("/api/meta/providers")
        assert response.status_code == 200
        data = response.json()
        assert "active_provider" in data
        assert "recent_outcomes" in data
        assert isinstance(data["recent_outcomes"], list)
