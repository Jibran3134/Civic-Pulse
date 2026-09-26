from app.providers.triage.base import Category, Priority, TriageProvider, TriageResult


class SimulatedTriage(TriageProvider):
    name = "simulated"

    def __init__(
        self,
        raise_exception: bool = False,
        fixed_category: Category = Category.WATER,
        fixed_priority: Priority = Priority.HIGH,
        fixed_summary: str = "Simulated triage result",
        fixed_confidence: float = 0.95,
    ):
        self.raise_exception = raise_exception
        self.fixed_category = fixed_category
        self.fixed_priority = fixed_priority
        self.fixed_summary = fixed_summary
        self.fixed_confidence = fixed_confidence

    async def triage(self, text: str, location: str) -> TriageResult:
        if self.raise_exception:
            raise RuntimeError("Simulated provider failure")
        return TriageResult(
            category=self.fixed_category,
            priority=self.fixed_priority,
            summary=self.fixed_summary,
            confidence=self.fixed_confidence,
            triaged_by="simulated",
        )