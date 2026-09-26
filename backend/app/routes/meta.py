from fastapi import APIRouter, Depends

from app.core.dependencies import get_triage_provider_dep
from app.core.logging import get_logger
from app.providers.triage.base import TriageProvider
from app.services.triage import TriageService

logger = get_logger(__name__)

router = APIRouter()


@router.get("/meta/providers")
async def get_providers(
    provider: TriageProvider = Depends(get_triage_provider_dep),
):
    TriageService()
    # Get the last 20 outcomes from the cache or in-memory
    # For now, return the active provider
    return {
        "active_provider": provider.name,
        "recent_outcomes": [],  # TODO: implement recent outcomes tracking
    }
