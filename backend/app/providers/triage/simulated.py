import re

from app.providers.triage.base import Category, Priority, TriageProvider, TriageResult


class SimulatedTriage(TriageProvider):
    name = "simulated"

    def __init__(
        self,
        raise_exception: bool = False,
        return_malformed: bool = False,
        fixed_category: Category | None = None,
        fixed_priority: Priority | None = None,
        fixed_summary: str | None = None,
        fixed_confidence: float = 0.95,
    ):
        self.raise_exception = raise_exception
        self.return_malformed = return_malformed
        self.fixed_category = fixed_category
        self.fixed_priority = fixed_priority
        self.fixed_summary = fixed_summary
        self.fixed_confidence = fixed_confidence

    async def triage(self, text: str, location: str) -> TriageResult:
        if self.raise_exception:
            raise RuntimeError("Simulated provider failure")

        if self.return_malformed:
            raise ValueError("Malformed output simulated: invalid category or syntax")

        # If explicit fixed values are provided, use them
        if self.fixed_category is not None:
            category = self.fixed_category
        else:
            # Deterministic keyword mapping for CI
            lower = text.lower()
            if any(k in lower for k in ["water", "pipe", "drain", "leak", "flood"]):
                category = Category.WATER
            elif any(k in lower for k in ["electric", "power", "wire", "spark", "transformer"]):
                category = Category.ELECTRICITY
            elif any(k in lower for k in ["waste", "trash", "garbage", "bin", "sewage"]):
                category = Category.SANITATION
            elif any(k in lower for k in ["road", "street", "pothole", "pavement"]):
                category = Category.ROADS
            elif any(k in lower for k in ["light", "lamp", "dark", "pole"]):
                category = Category.STREETLIGHTS
            else:
                category = Category.OTHER

        if self.fixed_priority is not None:
            priority = self.fixed_priority
        else:
            lower = text.lower()
            if any(k in lower for k in ["urgent", "danger", "burst", "flood", "emergency", "fire"]):
                priority = Priority.HIGH
            elif any(k in lower for k in ["minor", "request", "low"]):
                priority = Priority.LOW
            else:
                priority = Priority.NORMAL

        summary = self.fixed_summary or (text[:137] + "..." if len(text) > 140 else text)

        return TriageResult(
            category=category,
            priority=priority,
            summary=summary,
            confidence=self.fixed_confidence,
            triaged_by="simulated",
        )

