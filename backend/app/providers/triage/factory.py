from app.core.config import get_settings
from app.providers.triage.base import TriageProvider
from app.providers.triage.rules import RuleBasedTriage
from app.providers.triage.simulated import SimulatedTriage


def get_triage_provider(provider_name: str | None = None) -> TriageProvider:
    settings = get_settings()
    name = (provider_name or settings.triage_provider).strip().lower()

    if name == "simulated":
        return SimulatedTriage()
    if name == "rules":
        return RuleBasedTriage()
    if name in ("llm", "llm:groq"):
        from app.providers.triage.llm_groq import LLMTriage

        return LLMTriage()
    if name in ("ollama", "llm:ollama"):
        from app.providers.triage.ollama import OllamaTriage

        return OllamaTriage()

    # Default to simulated for safety in CI/unconfigured environments
    return SimulatedTriage()
