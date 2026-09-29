# CivicPulse AI Triage Layer Documentation

## 1. Overview
The CivicPulse triage layer automatically categorizes citizen complaints, assigns operational priority, and produces a concise one-line summary (maximum 140 characters).

The core design principle is **vendor independence and graceful degradation**: the rest of the application interacts with an abstract protocol, never directly with a specific language model.

---

## 2. Architecture & Contracts

### 2.1 Frozen Interface Contract (§2.5)
All triage providers implement the `TriageProvider` protocol (`backend/app/providers/triage/base.py`):

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

The frozen provider model contains exactly 4 fields (`category`, `priority`, `summary`, `confidence`). Operational metadata required for persistence (`triaged_by`, `triage_latency_ms`) is added at the service layer via `TriageOutcome(TriageResult)`.

### 2.2 Provider Selection (`TRIAGE_PROVIDER`)
The active provider is chosen via the `TRIAGE_PROVIDER` environment variable (§2.5 canonical values):

| Canonical Key | Aliases | Class | Target Environment | Characteristics |
| :--- | :--- | :--- | :--- | :--- |
| `llm` | `llm:groq` | `LLMTriage` | Production | Free-tier cloud inference via `llama-3.1-8b-instant`, ultra-low latency, PII redacted before send. |
| `ollama` | `llm:ollama` | `OllamaTriage` | Local / Offline | Containerized `llama3.2:1b`, zero internet reliance, zero external API keys. |
| `rules` | — | `RuleBasedTriage` | Fallback / Standalone | Deterministic keyword matching, always available, zero failure modes. |
| `simulated` | — | `SimulatedTriage` | CI / Testing | Seeded deterministic fake, no network, supports configurable failure injection. |

---

## 3. Engineering Around the Model (Resilience & Safety)

### 3.1 Hard 10-Second Timeout Cap (§2.5 item 2)
Under no circumstance may an LLM call block indefinitely. Both `LLMTriage` and `OllamaTriage` configure `httpx.AsyncClient(timeout=10.0)`. Requests exceeding 10 seconds are aborted and trigger immediate fallback.

### 3.2 Selective Jittered Retry (§2.5 item 3)
* **Retryable Errors**: HTTP 429 (rate limited), HTTP 5xx (server errors), and network timeouts.
* **Non-Retryable Errors**: HTTP 400 (bad request). A malformed request will always fail; retrying it wastes time and tokens.
* **Jitter**: Jitter between $0.2\text{ s}$ and $0.6\text{ s}$ is added before retrying to prevent synchronized retry storms.
* **Retry Count**: Exactly 1 retry. If the second attempt fails, the system immediately falls back.

### 3.3 Prompt-Injection Defense (§2.5 item 7)
Untrusted user input is isolated inside `<complaint_data><complaint_text>...</complaint_text></complaint_data>` XML tags. The system prompt instructs the model to ignore any instructions inside the complaint body. Downstream output is constrained strictly to predefined enums:
* **Category**: `water`, `electricity`, `sanitation`, `roads`, `streetlights`, `other`
* **Priority**: `high`, `normal`, `low`

Any hallucinated or injected category is rejected during Pydantic schema validation.

### 3.4 PII Redaction Before Send (ADR 004 / CLO 8)
Before any text is dispatched to external cloud servers (Groq), `redact_pii()` replaces:
* Pakistani phone numbers (`03xx-xxxxxxx`, `+92...`) with `[PHONE_REDACTED]`
* Email addresses with `[EMAIL_REDACTED]`
* 13-digit CNIC numbers with `[CNIC_REDACTED]`

### 3.5 Fallback Chain (§2.5 item 4)
The fallback architecture is a **direct fallback** from the active provider to `RuleBasedTriage`:
$$\text{Active Provider (Groq or Ollama)} \xrightarrow{\text{on failure}} \text{RuleBasedTriage } [\texttt{triaged\_by="rules:fallback"}]$$

*(Note: Ollama is an alternative offline provider, not an intermediate fallback tier.)*

When fallback occurs:
1. A structured JSON `WARNING` log is emitted to stdout with:
   - `complaint_id`
   - `provider`
   - `error_class`
   - `request_id`
2. `RuleBasedTriage` is executed synchronously.
3. The persisted record stores `triaged_by = "rules:fallback"`.
4. The citizen receives an HTTP 201 response — **never an HTTP 500**.

### 3.6 Confidence Semantics
* `LLMTriage` / `OllamaTriage`: Float returned by model in $[0.0, 1.0]$.
* `RuleBasedTriage`: Transparent keyword density score:
  * $\ge 3$ keyword matches $\to 0.9$
  * $1\text{–}2$ keyword matches $\to 0.6$
  * $0$ matches (default category/priority) $\to 0.3$
* `SimulatedTriage`: Deterministic $0.95$.

### 3.7 Latency Measurement Semantics
`triage_latency_ms` is measured using `time.perf_counter()` starting immediately before the cache lookup begins and ending when the final `TriageOutcome` is ready. It covers cache lookup, inference (including retry/fallback if triggered), and data transformation.

---

## 4. Redis Content-Hash Caching (§2.5 item 5)

* **Key Generation**: `triage:cache:{sha256(text.strip().lower() + "|" + location.strip().lower())}`
* **Time-to-Live (TTL)**: 24 hours ($86,400\text{ s}$).
* **Scope & Limitation**: Collapses exact duplicate submissions (e.g., rapid resubmissions, identical citizen reports, automated retries). Near-duplicate reports with varied wording will result in different SHA-256 digests and require separate inference (semantic deduplication requires embedding models, which is out of scope).
* **Metrics**:
  * `triage:stats:total_queries`
  * `triage:stats:cache_hits`
  * Measured hit rate is dynamically calculated as $\frac{\text{cache\_hits}}{\text{total\_queries}}$ and surfaced via `/api/meta/providers`.

---

## 5. Observability Surface (`GET /api/meta/providers`)

The endpoint exposes:
* `active_provider`: Name of the configured triage provider.
* `cache_stats`: Total queries, cache hits, cache misses, and hit rate percentage.
* `recent_outcomes`: The last 20 triage events, each containing `provider`, `latency_ms`, `fallback` (boolean), `cache_hit` (boolean), and ISO timestamp.
