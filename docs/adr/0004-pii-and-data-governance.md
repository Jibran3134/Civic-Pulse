# ADR 0004: PII and Data Governance for External LLM Triage

* **Status**: Accepted
* **Date**: 2026-09-26
* **Authors**: Alishba, Jibran
* **Context**: CivicPulse Assignment CS4032 (CLO 8)

---

## 1. Context and Problem Statement

CivicPulse collects public civic complaints to triage municipal issues (water leaks, power outages, damaged roads, broken streetlights). When citizens submit complaints, their raw input frequently includes personally identifiable information (PII), such as:
- Pakistani mobile telephone numbers (`0300-xxxxxxx`, `+92 3xx xxxxxxx`)
- Email addresses (`name@example.com`)
- Computerized National Identity Card (CNIC) numbers (`xxxxx-xxxxxxx-x`)
- Specific citizen names and private residential addresses.

Under the production architecture (`TRIAGE_PROVIDER=llm:groq`), the triage service invokes an external third-party API (Groq cloud hosting LLaMA 3.1 8B). Third-party and free-tier LLM providers often maintain retention windows or may use prompt payloads for continuous evaluation/training. Transmitting unredacted citizen PII to external third parties introduces severe privacy, compliance, and ethical risks.

---

## 2. Decision Drivers

1. **Citizen Privacy**: Protect citizens against accidental leakage of contact numbers and national identifiers.
2. **Regulatory & Governance Compliance**: Minimize data exposure to third-party processors (CLO 8 data governance).
3. **Model Accuracy**: Preserve enough contextual domain tokens (e.g., "pipe burst", "sparking wire", "flooding Street 12") so that model categorization and priority ranking remain accurate.
4. **Resilience & Latency**: PII scrubbing must be local, synchronous, low-latency, and zero-network overhead.

---

## 3. Considered Options

* **Option 1: Send Raw Complaint to LLM**: Zero preprocessing, but violates data governance standards and exposes citizen identities.
* **Option 2: Completely Local Processing (Ollama only)**: Ensures zero data leaves the machine, but requires heavy compute ($>4\text{ GB}$ RAM, GPU) and produces lower accuracy with 1B parameters.
* **Option 3: Redact PII Before External Transmission (Selected)**: Preprocess and sanitize the complaint text locally before dispatching to Groq API. Replace detected PII with semantic tokens (`[PHONE_REDACTED]`, `[EMAIL_REDACTED]`, `[CNIC_REDACTED]`).

---

## 4. Decision Outcome

**Chosen Option: Option 3 (Redact Before Sending)**.

Before any prompt is constructed for `LLMTriage` (Groq), the text and location strings are sanitized via `redact_pii()`:
1. Regex matching and masking for Pakistani phone formats.
2. Regex matching and masking for email addresses.
3. Regex matching and masking for 13-digit Pakistani CNIC numbers.
4. The database stores the original submission securely within the internal PostgreSQL store, but the external payload transmitted over the internet to Groq is strictly scrubbed of identifiers.

### What Leaves the Machine
- Scrubbed municipal complaint description (e.g., "Water pipe burst flooding street, contact [PHONE_REDACTED]").
- Generalized location (e.g., "Mall Road, Lahore").
- System prompts and expected JSON response schemas.

### What Never Leaves the Machine
- Citizen contact phone numbers.
- Citizen email addresses.
- CNIC / National ID numbers.
- Database credentials and internal IDs.

---

## 5. Consequences

### Positive
* **Zero PII Exposure**: Third-party LLM providers never receive citizen contact info or identification numbers.
* **Preserved Classification Fidelity**: Municipal keywords and situational severity are intact; classification accuracy is unaffected.
* **Defensible in Viva**: Clearly articulates CLO 8 considerations and tradeoffs between cloud inference speed and data stewardship.

### Negative / Trade-offs
* Simple regex filters might miss unconventional PII disclosures (e.g., names written in free prose without prefixes).
* Small CPU overhead ($<1\text{ ms}$) during regex evaluation, which is negligible compared to network inference latency.
