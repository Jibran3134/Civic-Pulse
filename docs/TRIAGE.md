# CivicPulse AI Triage Layer Documentation

## 1. Overview
The CivicPulse triage layer automatically categorizes citizen complaints, assigns operational priority, and produces a concise one-line summary (maximum 140 characters).

The core design principle is **vendor independence and graceful degradation**: the rest of the application interacts with an abstract protocol, never directly with a specific language model.

---

## 2. Architecture & Providers

All triage providers implement the `TriageProvider` protocol (`backend/app/providers/triage/base.py`):

```python
class TriageProvider(Protocol):
    name: str
    async def triage(self, text: str, location: str) -> TriageResult: ...
```

The active provider is chosen via the `TRIAGE_PROVIDER` environment variable:

| Provider Key | Class | Target Environment | Characteristics |
| :--- | :--- | :--- | :--- |
| `llm:groq` | `LLMTriage` | Production | Free-tier cloud inference via `llama-3.1-8b-instant`, ultra-low latency, PII redacted. |
| `llm:ollama` | `OllamaTriage` | Local / Offline | Containerized `llama3.2:1b`, zero internet reliance, zero API keys. |
| `rules` | `RuleBasedTriage` | Fallback / Standalone | Deterministic keyword matching, always available, zero failure modes. |
| `simulated` | `SimulatedTriage` | CI / Testing | Seeded deterministic fake, no network, supports configurable failure injection. |

---

## 3. Engineering Around the Model (Resilience & Safety)

### 3.1 Hard 10-Second Timeout Cap
Under no circumstance may an LLM call block indefinitely. Both `LLMTriage` and `OllamaTriage` configure `httpx.AsyncClient(timeout=10.0)`. Requests exceeding 10 seconds are aborted and trigger immediate fallback.

### 3.2 Selective Jittered Retry
* **Retryable Errors**: HTTP 429 (rate limited), HTTP 5xx (server errors), and timeouts.
* **Non-Retryable Errors**: HTTP 400 (bad request). A malformed request will always fail; retrying it wastes time and tokens.
* **Jitter**: Jitter between $0.2\text{ s}$ and $0.6\text{ s}$ is added before retrying to prevent synchronised retry storms.
* **Retry Count**: Exactly 1 retry. If the second attempt fails, the system immediately falls back.

### 3.3 Prompt-Injection Defense
Untrusted user input is isolated inside `<complaint_data><complaint_text>...</complaint_text></complaint_data>` XML tags. The system prompt instructs the model to ignore any instructions inside the complaint body. Downstream output is constrained strictly to the predefined enums:
* **Category**: `water`, `electricity`, `sanitation`, `roads`, `streetlights`, `other`
* **Priority**: `high`, `normal`, `low`

Any hallucinated or injected category is rejected during Pydantic schema validation.

### 3.4 PII Redaction (ADR 004 / CLO 8)
Before any text is dispatched to Groq's cloud servers, `redact_pii()` replaces:
* Pakistani phone numbers (`03xx-xxxxxxx`, `+92...`) with `[PHONE_REDACTED]`
* Email addresses with `[EMAIL_REDACTED]`
* 13-digit CNIC numbers with `[CNIC_REDACTED]`

### 3.5 Graceful Fallback (`rules:fallback`)
If an AI provider fails for any reason (timeout, quota exhaustion, network partition, or unparseable output):
1. A structured WARNING log is emitted containing the `complaint_id`, `provider`, and `error_class`.
2. `RuleBasedTriage` is invoked instantly.
3. The persisted record stores `triaged_by = "rules:fallback"`.
4. The citizen receives an HTTP 201 response — **never an HTTP 500**.

---

## 4. Redis Content-Hash Caching

Duplicate complaints (e.g., several neighbours reporting the same burst water pipe) are common during municipal incidents.

* **Key Generation**: `triage:cache:{sha256(text.strip().lower() + "|" + location.strip().lower())}`
* **Time-to-Live (TTL)**: 24 hours ($86,400\text{ s}$).
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
