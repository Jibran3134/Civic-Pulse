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

---

## Operations & Infrastructure

### 1. How to Deploy

#### A. Local Development (Docker Compose)
```bash
# Start all 5 services with automated migrations and seed data
docker compose up -d

# Verify readiness of all services
curl http://localhost:8000/ready
```

#### B. Kubernetes (k3d / Production Cluster)
```bash
# Apply kustomize overlay for production
kubectl apply -k k8s/overlays/prod

# Verify pod status and rollout progress
kubectl rollout status deployment/backend -n civicpulse
kubectl get pods -n civicpulse
```

---

### 2. How to Roll Back

#### A. Kubernetes Automated Rollback
If a newly deployed image fails health checks or introduces regressions:

```bash
# View rollout revision history
kubectl rollout history deployment/backend -n civicpulse

# Undo deployment and revert to the immediate previous revision
kubectl rollout undo deployment/backend -n civicpulse

# Revert to a specific revision (e.g., revision 2)
kubectl rollout undo deployment/backend --to-revision=2 -n civicpulse

# Confirm rollback completion
kubectl rollout status deployment/backend -n civicpulse
```

#### B. Git / Docker Compose Rollback
```bash
# Revert to the last known stable Git tag or commit
git checkout <previous-tag-or-commit-sha>

# Restart containers using immutable image digests
docker compose -f compose.prod.yaml up -d
```

---

### 3. How to Read Logs

#### A. Docker Compose
```bash
# Stream all logs with timestamps
docker compose logs -f -t

# Stream structured JSON logs for the backend only
docker compose logs -f backend

# Stream Redis or PostgreSQL logs
docker compose logs -f redis
docker compose logs -f postgres
```

#### B. Kubernetes
```bash
# Stream backend application logs from all replicas
kubectl logs -l app=backend -n civicpulse -f --tail=100

# Filter for fallback warnings or errors
kubectl logs -l app=backend -n civicpulse | grep "triage_fallback"
```

---

### 4. What to Do When Triage Fails

1. **Verify if fallback triggered**:
   Query the provider metadata endpoint:
   ```bash
   curl http://localhost:8000/api/meta/providers
   ```
   Check the `recent_outcomes` array. If `fallback: true` and `provider: "rules:fallback"`, the system is safely operating on the local deterministic heuristic engine.

2. **Inspect the error class in the warning log**:
   Check backend logs for the structured warning:
   ```json
   {"event": "triage_fallback", "complaint_id": "...", "provider": "llm:groq", "error_class": "HTTPStatusError"}
   ```
   - **`HTTPStatusError (401/403)`**: Invalid or expired `GROQ_API_KEY`. Update key in `.env` or Kubernetes secret.
   - **`HTTPStatusError (429)`**: Rate limit exceeded. The system will automatically use Redis cache and rules fallback.
   - **`TimeoutException`**: Network latency exceeded 10.0s. Check egress connectivity.

3. **Switch to offline Ollama container**:
   If cloud LLM is down indefinitely, switch to local Ollama:
   ```bash
   # In .env or Kubernetes ConfigMap:
   TRIAGE_PROVIDER=ollama
   ```
   Restart backend service: `docker compose restart backend`.

