from fastapi import APIRouter, Depends

from app.core.dependencies import get_triage_provider_dep
from app.core.logging import get_logger
from app.providers.triage.base import TriageProvider
from app.services.status_machine import transition_table
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


@router.get(
    "/meta/status-transitions",
    responses={
        200: {
            "description": (
                "The workflow state machine, so a client can render the available "
                "operator actions without hard-coding them."
            )
        }
    },
)
async def get_status_transitions():
    """Expose VALID_TRANSITIONS.

    The dashboard needs to know which buttons to draw. Serving the table is
    what keeps the backend the single source of truth for the workflow, rather
    than the frontend branching on the current status to guess.
    """
    return {"transitions": transition_table()}

