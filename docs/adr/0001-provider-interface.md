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
class TriageResult(BaseModel):
    category: Category
    priority: Priority
    summary: str = Field(max_length=140)
    confidence: float = Field(ge=0.0, le=1.0)

class TriageProvider(Protocol):
    name: str
    async def triage(self, text: str, location: str) -> TriageResult: ...
```

Four distinct implementations conform to this protocol:
1. `LLMTriage` (canonical: `llm`, alias: `llm:groq`): Production path calling Groq's `llama-3.1-8b-instant`.
2. `OllamaTriage` (canonical: `ollama`, alias: `llm:ollama`): Offline path running local `llama3.2:1b` container in Docker Compose.
3. `RuleBasedTriage` (`rules`): Deterministic keyword fallback that always succeeds.
4. `SimulatedTriage` (`simulated`): Deterministic fake for CI, supporting seeded responses and configurable failure injection.

Operational metadata (`triaged_by`, `triage_latency_ms`) is encapsulated at the service level via `TriageOutcome(TriageResult)`.
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

---

## 5. Update — 2026-09-27: Centralised Provider Configuration (feat/ollama-retry)

**Author**: Alishba

Prior to this update, `OllamaTriage` hard-coded its base URL, model name and
timeout, while `LLMTriage` read some values from environment variables
directly and others from `Settings`.  This caused the two providers to drift:
`OllamaTriage` had no retry logic at all, and its timeout was always 10 s
regardless of any `.env` override.

### Change

All six provider-level tunables have been moved into `Settings`
(`backend/app/core/config.py`) and are read by both providers via
`get_settings()`:

| Setting field            | Env var                  | Default              |
|--------------------------|--------------------------|----------------------|
| `ollama_base_url`        | `OLLAMA_BASE_URL`        | `http://localhost:11434` |
| `ollama_model`           | `OLLAMA_MODEL`           | `llama3.2:1b`        |
| `triage_timeout`         | `TRIAGE_TIMEOUT`         | `10.0` (max 10 s)    |
| `triage_max_retries`     | `TRIAGE_MAX_RETRIES`     | `1`                  |
| `triage_retry_base_delay`| `TRIAGE_RETRY_BASE_DELAY`| `0.5`                |
| `triage_cache_ttl_hours` | `TRIAGE_CACHE_TTL_HOURS` | `24`                 |

`triage_timeout` carries a Pydantic `le=10.0` constraint; `triage_max_retries`
carries `ge=0`.  Neither provider can now exceed the spec cap or be configured
with a negative retry count — validation is enforced at start-up, not
discovered at the first live call.

`OllamaTriage` was also given the same jittered retry logic as `LLMTriage`
(retry on timeout, 429, 5 xx; never on another 4 xx; never on a parse
validation error).
