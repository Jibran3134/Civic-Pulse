import pytest
import pytest_asyncio
from httpx import ASGITransport, AsyncClient

from app.main import app


@pytest_asyncio.fixture
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
