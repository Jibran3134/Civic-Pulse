import re

from app.providers.triage.base import Category, Priority, TriageProvider, TriageResult

CATEGORY_KEYWORDS = {
    Category.WATER: [
        "water", "pipe", "leak", "flood", "drain", "sewer", "burst", "main",
        "supply", "tap", "faucet", "drainage", "blockage", "overflow"
    ],
    Category.ELECTRICITY: [
        "electric", "power", "light", "outage", "blackout", "wire", "cable",
        "transformer", "meter", "voltage", "current", "short circuit", "spark"
    ],
    Category.SANITATION: [
        "garbage", "trash", "waste", "bin", "collection", "dump", "litter",
        "rubbish", "refuse", "sanitation", "toilet", "sewage", "smell"
    ],
    Category.ROADS: [
        "road", "street", "pothole", "crack", "asphalt", "pavement", "traffic",
        "sign", "signal", "intersection", "crossing", "speed bump", "repair"
    ],
    Category.STREETLIGHTS: [
        "streetlight", "lamp", "light pole", "bulb", "dark", "lighting",
        "illumination", "outage", "flicker", "broken light"
    ],
}

PRIORITY_KEYWORDS = {
    Priority.HIGH: [
        "urgent", "emergency", "danger", "hazard", "risk", "immediate",
        "critical", "severe", "flooding", "burst", "collapse", "fire",
        "gas leak", "electrocution", "accident", "injury"
    ],
    Priority.LOW: [
        "minor", "cosmetic", "aesthetic", "suggestion", "feedback",
        "request", "inquiry", "question", "information"
    ],
}


class RuleBasedTriage(TriageProvider):
    name = "rules"

    def __init__(self):
        self._category_patterns = {
            cat: [re.compile(rf"\b{re.escape(kw)}\b", re.IGNORECASE) for kw in kws]
            for cat, kws in CATEGORY_KEYWORDS.items()
        }
        self._priority_patterns = {
            pri: [re.compile(rf"\b{re.escape(kw)}\b", re.IGNORECASE) for kw in kws]
            for pri, kws in PRIORITY_KEYWORDS.items()
        }

    def _classify(self, text: str, patterns: dict) -> str | None:
        scores: dict[str, int] = {}
        for category, pattern_list in patterns.items():
            score = sum(1 for pattern in pattern_list if pattern.search(text))
            if score > 0:
                scores[category.value] = score
        return max(scores, key=lambda k: scores[k]) if scores else None

    async def triage(self, text: str, location: str) -> TriageResult:
        full_text = f"{text} {location}".lower()

        category_str = self._classify(full_text, self._category_patterns)
        category = Category(category_str) if category_str else Category.OTHER

        priority_str = self._classify(full_text, self._priority_patterns)
        priority = Priority(priority_str) if priority_str else Priority.NORMAL

        # Generate summary
        words = text.split()
        summary = " ".join(words[:20]) + ("..." if len(words) > 20 else "")
        if len(summary) > 140:
            summary = summary[:137] + "..."

        # Determine confidence from keyword match density
        # 0.9 if >=3 keyword matches, 0.6 for 1-2 matches, 0.3 for default/unmatched
        category_matches = sum(
            1 for patterns in self._category_patterns.values() for p in patterns if p.search(full_text)
        )
        priority_matches = sum(
            1 for patterns in self._priority_patterns.values() for p in patterns if p.search(full_text)
        )
        total_matches = category_matches + priority_matches

        if total_matches >= 3:
            confidence = 0.9
        elif total_matches >= 1:
            confidence = 0.6
        else:
            confidence = 0.3

        return TriageResult(
            category=category,
            priority=priority,
            summary=summary,
            confidence=confidence,
        )
