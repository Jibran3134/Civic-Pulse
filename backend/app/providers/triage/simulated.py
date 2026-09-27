import re

from app.providers.triage.base import Category, Priority, TriageProvider, TriageResult

_CATEGORY_KEYWORDS: list[tuple[list[str], Category]] = [
    (["water", "pipe", "drain", "leak", "flood"], Category.WATER),
    (["electric", "power", "wire", "spark", "transformer"], Category.ELECTRICITY),
    (["waste", "trash", "garbage", "bin", "sewage"], Category.SANITATION),
    (["road", "street", "pothole", "pavement"], Category.ROADS),
    (["light", "lamp", "dark", "pole"], Category.STREETLIGHTS),
]

_PRIORITY_KEYWORDS: list[tuple[list[str], Priority]] = [
    (["urgent", "danger", "burst", "flood", "emergency", "fire"], Priority.HIGH),
    (["minor", "request", "low"], Priority.LOW),
]


def _detect_category(lower: str) -> Category:
    for keywords, cat in _CATEGORY_KEYWORDS:
        if any(k in lower for k in keywords):
            return cat
    return Category.OTHER


def _detect_priority(lower: str) -> Priority:
    for keywords, pri in _PRIORITY_KEYWORDS:
        if any(k in lower for k in keywords):
            return pri
    return Priority.NORMAL


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

        lower = text.lower()
        category = self.fixed_category if self.fixed_category is not None else _detect_category(lower)
        priority = self.fixed_priority if self.fixed_priority is not None else _detect_priority(lower)
        summary = self.fixed_summary or (text[:137] + "..." if len(text) > 140 else text)

        return TriageResult(
            category=category,
            priority=priority,
            summary=summary,
            confidence=self.fixed_confidence,
        )

