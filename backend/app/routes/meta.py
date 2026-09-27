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
    triage_service = TriageService(provider=provider)
    recent_outcomes = await triage_service.get_recent_outcomes(limit=20)
    cache_stats = await triage_service.get_cache_stats()

    return {
        "active_provider": provider.name,
        "recent_outcomes": recent_outcomes,
        "cache_stats": cache_stats,
    }

