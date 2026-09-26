import os
import httpx

from app.providers.triage.base import Category, Priority, TriageProvider, TriageResult


class OllamaTriage(TriageProvider):
    name = "llm:ollama"

    def __init__(self):
        # Use host.docker.internal to reach Ollama on host from Docker container
        self.base_url = os.getenv("OLLAMA_BASE_URL", "http://host.docker.internal:11434")
        self.model = os.getenv("OLLAMA_MODEL", "llama3.2:1b")
        self._client = httpx.AsyncClient(timeout=30.0)

    async def triage(self, text: str, location: str) -> TriageResult:
        prompt = f"""Classify this municipal complaint into a category and priority.

Categories: water, electricity, sanitation, roads, streetlights, other
Priorities: high, normal, low

Complaint: {text}
Location: {location}

Respond with JSON only:
{{
  "category": "water|electricity|sanitation|roads|streetlights|other",
  "priority": "high|normal|low",
  "summary": "one-line summary (max 140 chars)",
  "confidence": 0.0-1.0
}}"""

        try:
            response = await self._client.post(
                f"{self.base_url}/api/generate",
                json={
                    "model": self.model,
                    "prompt": prompt,
                    "stream": False,
                    "format": "json",
                    "options": {"temperature": 0.1},
                },
            )
            response.raise_for_status()
            data = response.json()

            import json
            result = json.loads(data.get("response", "{}"))

            return TriageResult(
                category=Category(result.get("category", "other")),
                priority=Priority(result.get("priority", "normal")),
                summary=result.get("summary", text[:140]),
                confidence=result.get("confidence", 0.5),
                triaged_by="llm:ollama",
            )
        except Exception as e:
            # Fallback to rules on any error
            from app.providers.triage.rules import RuleBasedTriage
            fallback = RuleBasedTriage()
            result = await fallback.triage(text, location)
            result.triaged_by = "rules:fallback"
            return result

    async def close(self):
        await self._client.aclose()