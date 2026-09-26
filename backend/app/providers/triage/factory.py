
from app.core.config import get_settings
from app.providers.triage.base import TriageProvider
from app.providers.triage.rules import RuleBasedTriage
from app.providers.triage.simulated import SimulatedTriage


def get_triage_provider(provider_name: str | None = None) -> TriageProvider:
    settings = get_settings()
    name = provider_name or settings.triage_provider

    if name == "simulated":
        return SimulatedTriage()
    elif name == "rules":
        return RuleBasedTriage()
    elif name == "llm:groq":
        from app.providers.triage.llm_groq import LLMTriage
        return LLMTriage()
    elif name == "llm:ollama":
        from app.providers.triage.ollama import OllamaTriage
        return OllamaTriage()
    else:
        # Default to simulated for safety
        return SimulatedTriage()
