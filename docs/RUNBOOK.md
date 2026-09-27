# CivicPulse Runbook — AI Layer & Frontend

> **Scope**: This document covers the AI triage layer and the React frontend.
> Infra, database, Redis and Kubernetes sections are maintained separately
> by Jibran and will be merged into this file.

---

## AI Layer

### Prerequisites

| Service | Default address |
|---------|----------------|
| Backend API | `http://localhost:8000` |
| Ollama (local) | `http://localhost:11434` |

### Start the backend in development

```bash
cd backend
cp .env.example .env          # set DATABASE_URL, REDIS_URL, TRIAGE_PROVIDER
uvicorn app.main:app --reload
```

Key environment variables for the AI layer:

| Variable | Purpose | Default |
|---|---|---|
| `TRIAGE_PROVIDER` | Which provider to use: `simulated`, `rules`, `llm`, `ollama` | `simulated` |
| `GROQ_API_KEY` | Required when `TRIAGE_PROVIDER=llm` | _(empty)_ |
| `OLLAMA_BASE_URL` | Ollama server address | `http://localhost:11434` |
| `OLLAMA_MODEL` | Model tag to request from Ollama | `llama3.2:1b` |
| `TRIAGE_TIMEOUT` | Per-call HTTP timeout in seconds (max 10) | `10` |
| `TRIAGE_MAX_RETRIES` | Retry attempts after first failure | `1` |
| `TRIAGE_RETRY_BASE_DELAY` | Base back-off in seconds (±40 % jitter) | `0.5` |
| `TRIAGE_CACHE_TTL_HOURS` | Content-hash cache TTL | `24` |

### Run Ollama locally

```bash
# Pull the model once
ollama pull llama3.2:1b

# Confirm it responds
curl http://localhost:11434/api/tags
```

Set `TRIAGE_PROVIDER=ollama` in `.env`.  The backend will then send
classification requests to Ollama instead of Groq.

### Use Groq (cloud LLM)

```bash
# .env
TRIAGE_PROVIDER=llm
GROQ_API_KEY=gsk_...
```

Never commit a real key.  The field defaults to empty; the provider raises
`ValueError("GROQ_API_KEY is not configured")` and the service falls back
to `RuleBasedTriage`.

### Retry behaviour

Both `LLMTriage` and `OllamaTriage` share the same retry policy (§2.5 item 3):

* Retried: timeout, HTTP 429, HTTP 5xx
* Not retried: HTTP 400 or any other 4xx, parse/validation failures
* After all retries exhausted: `TriageService` catches the exception and invokes
  `RuleBasedTriage`.  The complaint is saved with `triaged_by="rules:fallback"`.

### Run the triage test suite

```bash
cd backend   # must run from inside backend/
pytest tests/test_triage.py tests/test_ollama.py -v
```

No Redis and no Ollama server are required; all HTTP calls are mocked.

### Cache

Triage results are cached in Redis by content hash (SHA-256 of
`text.lower() | location.lower()`) for `TRIAGE_CACHE_TTL_HOURS` hours (default
24 h).  A cache hit bypasses the LLM entirely.

Check cache stats:

```bash
curl http://localhost:8000/api/triage/outcomes
```

---

## Frontend

### Prerequisites

| Tool | Version |
|---|---|
| Node.js | ≥ 18 |
| npm | ≥ 9 |

### Start the dev server

```bash
cd frontend
npm install
npm run dev
```

The Vite dev server runs on `http://localhost:5173` by default and proxies
`/api` requests to `http://localhost:8000` (configured in `vite.config.ts`).

### Environment variables (frontend)

| Variable | Purpose | Default |
|---|---|---|
| `VITE_API_URL` | Backend API base URL (build-time) | _(proxy, no explicit value needed in dev)_ |

### Run frontend tests

```bash
cd frontend
npm test
```

Tests use Vitest + Testing Library.  No backend connection is needed; the
API is mocked.

### Build production bundle

```bash
cd frontend
npm run build        # output -> dist/
```

The Docker image (`frontend/Dockerfile`) runs this at image build time.
Do not run `npm run build` locally unless you are validating the production
output; the dev server is faster for regular work.

### Common issues

| Symptom | Cause | Fix |
|---|---|---|
| `ECONNREFUSED localhost:8000` in browser | Backend not running | `cd backend && uvicorn app.main:app --reload` |
| Blank dashboard / 0 complaints | Database empty | `cd backend && python scripts/seed.py` |
| Category/priority badges not rendering | Types not re-exported | Check `frontend/src/types/index.ts` |
| `GROQ_API_KEY is not configured` in logs | Missing env var | Set in `.env` or use `TRIAGE_PROVIDER=simulated` |
