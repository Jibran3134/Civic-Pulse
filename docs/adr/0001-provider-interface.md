# ADR 0001: Pluggable TriageProvider Interface

* **Status**: Accepted
* **Date**: 2026-09-26
* **Authors**: Alishba, Jibran
* **Context**: CivicPulse Assignment CS4032 (§2.5)

---

## 1. Context and Problem Statement

In civic complaint platforms, classification mechanisms evolve continuously: today a keyword heuristic rule, tomorrow a hosted cloud language model (Groq), next month an on-premise SLM container (Ollama), and in automated testing a deterministic mock (Simulated). 

Coupling business services, API routes, or databases to a specific AI vendor produces vendor lock-in, unreliability when third parties experience outages or rate limits, and flaky non-deterministic automated testing pipelines.

---

## 2. Decision Drivers

1. **Interchangeability**: The system must switch triage mechanisms without rewriting backend logic.
2. **Determinism in CI**: Automated testing must never rely on live external networks or free-tier quotas.
3. **Fault Tolerance**: A third-party rate limit (HTTP 429) or network timeout must never crash citizen submission ($500$).
4. **Unified Schema Validation**: Downstream services must always receive strongly typed, verified output.

---

## 3. Decision Outcome

We implement an explicit **Interface / Protocol pattern** using Python's `typing.Protocol` and Pydantic v2:

```python
class TriageProvider(Protocol):
    name: str
    async def triage(self, text: str, location: str) -> TriageResult: ...
```

Four distinct implementations conform to this protocol:
1. `LLMTriage` (`llm:groq`): Production path calling Groq's `llama-3.1-8b-instant`.
2. `OllamaTriage` (`llm:ollama`): Offline path running local `llama3.2:1b` container in Docker Compose.
3. `RuleBasedTriage` (`rules`): Deterministic keyword fallback that always succeeds.
4. `SimulatedTriage` (`simulated`): Deterministic fake for CI, supporting seeded responses and configurable failure injection.

The active provider is chosen at runtime by the `TRIAGE_PROVIDER` environment variable via `get_triage_provider()`.

### Fault Isolation & Fallback Policy
* When any provider raises an error, times out ($>10\text{ s}$), or returns malformed JSON, `TriageService` automatically catches the exception, logs a warning with the error class and provider, and seamlessly invokes `RuleBasedTriage`.
* The persisted record explicitly registers `triaged_by = "rules:fallback"`, ensuring end users always receive a successful `201 Created`.

---

## 4. Consequences

### Positive
* **CI Determinism**: Tests pin `TRIAGE_PROVIDER=simulated`, eliminating flaky runs and external network dependence.
* **Resilience**: Zero 500 errors during third-party LLM outages or rate limits.
* **Separation of Concerns**: Routes and repositories remain completely unaware of whether an LLM or keyword engine classified the complaint.

### Negative / Trade-offs
* Requires maintaining four separate provider implementations.
* Keyword fallback provides coarser summaries than LLMs, though priority and category classification remain reliable.
