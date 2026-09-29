# CivicPulse Runbook

> **Scope**: Single operational reference for the whole platform — AI triage
> layer, React frontend, data layer, cache layer, container orchestration,
> Kubernetes and CI/CD.
>
> **Ownership**: Alishba owns §1 (AI Layer) and §2 (Frontend).
> Jibran owns §3–§8. The Troubleshooting Matrix (§9) is joint.
> Every procedure here is exercised by one owner or the other; both must be
> able to run anything in this document during a viva.

## Contents

| § | Section | Owner |
|---|---|---|
| 1 | [AI Layer](#1-ai-layer) | Alishba |
| 2 | [Frontend](#2-frontend) | Alishba |
| 3 | [Data Layer](#3-data-layer) | Jibran |
| 4 | [Cache & Rate Limiting](#4-cache--rate-limiting) | Jibran |
| 5 | [Deployment](#5-deployment) | Jibran |
| 6 | [Rollback](#6-rollback) | Jibran |
| 7 | [Logging & Metrics](#7-logging--metrics) | Jibran |
| 8 | [CI/CD Pipelines](#8-cicd-pipelines) | Jibran |
| 9 | [Troubleshooting Matrix](#9-troubleshooting-matrix) | Joint |

## Service map

| Service | Address (local) | In-cluster | Purpose |
|---|---|---|---|
| Backend API | `http://localhost:8000` | `http://backend:8000` | FastAPI, 4-layer |
| Frontend | `http://localhost:5173` | `http://frontend:80` | Vite dev / nginx prod |
| PostgreSQL 16 | `localhost:5432` | `postgres:5432` | System of record |
| Redis 7 | `localhost:6379` | `redis:6379` | Stats cache + rate limiter |
| Ollama (optional) | `http://localhost:11434` | `http://ollama:11434` | Offline LLM provider |
| `migrate` (Compose only) | — | — | One-shot Alembic job, exits on success |
| Groq (cloud) | `api.groq.com` | — | Primary LLM provider |

Namespaces: `civicpulse` (workloads), `ingress-nginx`, `kube-system`.

---

## 1. AI Layer

*Owner: Alishba. Provider implementations in `backend/app/providers/triage/`.*

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

### Triage result cache

> This is the **triage content-hash cache** (Redis key from complaint text), not
> the stats aggregate cache. See §4.1 for that one.

Triage results are cached in Redis by content hash (SHA-256 of
`text.lower() | location.lower()`) for `TRIAGE_CACHE_TTL_HOURS` hours (default
24 h).  A cache hit bypasses the LLM entirely and is recorded in
`triage_total{outcome="cached"}`.

Check cache stats. There is no dedicated cache endpoint — the outcomes are
served by the providers metadata endpoint, and hit/miss is a metric label:

```bash
# recent_outcomes, with cached entries flagged
curl http://localhost:8000/api/meta/providers

# Cache hits vs real inference
curl -s http://localhost:8000/metrics | grep '^triage_total'
```

---

## 2. Frontend

*Owner: Alishba. Source in `frontend/src/` — Submit, Dashboard, Stats views.*

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

## 3. Data Layer

*Owner: Jibran. PostgreSQL 16 via SQLAlchemy 2.0 async + Alembic migrations.*

### Apply migrations

No DDL runs at application startup. Schema is owned entirely by Alembic, so a
migrating deployment is always an explicit step.

```bash
cd backend

# Show current revision without applying anything
alembic current

# Apply everything to head
alembic upgrade head

# Inspect history
alembic history --verbose
```

### Rolling back a migration

```bash
alembic downgrade -1        # step back one revision
alembic downgrade <base>    # tear down to empty
```

> Downgrades are not always reversible. Check the migration file in
> `backend/alembic/versions/` for a working `downgrade()` before running one in
> anger. A dropped column will not come back with its data.

### Seed data

The seed is **idempotent** — it loads 30 Urdu-influenced English complaints
across all categories. Running it twice does not duplicate rows.

```bash
cd backend
python scripts/seed.py
```

No arguments, no flags. If the table is already populated the count guard exits
early rather than inserting again.

### Verifying the schema

```bash
# Indexes that must exist (status, priority) and (created_at)
psql "$DATABASE_URL" -c "\di complaints*"

# Row count and category spread
psql "$DATABASE_URL" -c "SELECT category, count(*) FROM complaints GROUP BY 1 ORDER BY 2 DESC;"

# Status distribution (drives the dashboard)
psql "$DATABASE_URL" -c "SELECT status, count(*) FROM complaints GROUP BY 1;"
```

### Database diagnostics

```bash
# Active connections and their state
psql "$DATABASE_URL" -c "SELECT state, count(*) FROM pg_stat_activity GROUP BY 1;"

# Long-running queries (a common cause of /ready timeouts)
psql "$DATABASE_URL" -c \
  "SELECT pid, now()-query_start AS duration, left(query,80)
   FROM pg_stat_activity WHERE state='active' AND now()-query_start > '1s'
   ORDER BY duration DESC;"

# Table bloat / dead tuples after heavy load testing
psql "$DATABASE_URL" -c \
  "SELECT relname, n_dead_tup, n_live_tup FROM pg_stat_user_tables ORDER BY n_dead_tup DESC;"
```

### Common issues

| Symptom | Cause | Fix |
|---|---|---|
| `relation "complaints" does not exist` | Migrations never applied | `alembic upgrade head` |
| `DuplicateObject: type "complaint_category" already exists` | Enum type pre-exists (stale DB) | Drop and recreate the database, then re-run migrations |
| Seed exits without inserting | Table already populated | Expected — the guard is doing its job |
| Dashboard empty in the browser | Backend up, DB empty | `python scripts/seed.py` |
| `/ready` returns 503 with `database` unhealthy | Connection refused or bad `DATABASE_URL` | Check `DATABASE_URL` in `.env` / Secret |

---

## 4. Cache & Rate Limiting

*Owner: Jibran. Redis 7 does two independent jobs — see `backend/app/providers/cache.py`.*

Redis is not a single-purpose cache here. Two separate client pools and two
separate key namespaces, so one cannot evict or trip the other:

| Job | Client | Key namespace | Failure behaviour |
|---|---|---|---|
| Stats read-through cache | `get_redis_client()` | stats keys | Degrades to a direct DB read |
| Distributed rate limiter | `get_rate_limit_client()` | limiter keys | Configurable, see below |

### 4.1 Stats cache

Aggregates are cached for **30 s** by default. Every stats response carries an
`X-Cache: HIT` or `X-Cache: MISS` header so cache behaviour is observable
without reading server logs.

```bash
# First call populates the cache -> MISS
curl -i http://localhost:8000/api/stats | grep -i x-cache

# Second call inside the 30s window -> HIT
curl -i http://localhost:8000/api/stats | grep -i x-cache

# Confirm the key exists in Redis
redis-cli KEYS 'stats*'
redis-cli TTL <the-key>
```

Writes invalidate the cache rather than updating it, so a `PATCH` or `POST`
never leaves a stale aggregate visible for the remainder of the TTL.

### 4.2 Rate limiter

Token bucket, evaluated in Redis so the limit holds across all backend
replicas. Client identity is the caller's IP.

| Variable | Purpose | Default |
|---|---|---|
| `RATE_LIMIT_REQUESTS` | Sustained token refill rate per window | `10` |
| `RATE_LIMIT_WINDOW` | Window length in seconds | `60` |
| `RATE_LIMIT_BURST` | Bucket depth, absorbs short spikes | `5` |
| `RATE_LIMIT_ENABLED` | Master switch | `true` |
| `RATE_LIMIT_FAIL_CLOSED` | Behaviour when Redis is unreachable | `false` |

`RATE_LIMIT_FAIL_CLOSED` is the one to think about before changing. `false`
means Redis being down lets traffic through (availability-first, no protection).
`true` means Redis being down rejects traffic (protection-first, total outage).
The default is deliberately availability-first for a civic complaint intake
system — a resident should not be unable to report a burst water main because
the cache is degraded.

Exceeding the limit returns **HTTP 429** with a `Retry-After` header carrying
the seconds until a token frees up. Clients that respect `Retry-After` recover
cleanly; clients that ignore it will see repeated 429s.

```bash
# Verify the 429 and its Retry-After header (should trip on the 11th request)
for i in $(seq 1 12); do
  curl -s -o /dev/null -w "req $i -> %{http_code}\n" \
    http://localhost:8000/api/complaints?limit=1
done

# Show the Retry-After value on the rejected request
curl -i http://localhost:8000/api/complaints?limit=1 | grep -i retry-after

# Inspect the live bucket state
redis-cli KEYS 'ratelimit*'
```

### 4.3 Redis diagnostics

```bash
# Health
redis-cli PING

# Memory and eviction policy (should be allkeys-lru)
redis-cli INFO memory | grep -E "used_memory_human|maxmemory_policy"

# Key count by namespace
redis-cli --scan --pattern 'stats*' | wc -l
redis-cli --scan --pattern 'ratelimit*' | wc -l

# What is using the memory
redis-cli INFO keyspace
redis-cli --bigkeys
```

### Common issues

| Symptom | Cause | Fix |
|---|---|---|
| `X-Cache: MISS` on every request | Cache writes failing | Check `redis-cli PING` and `REDIS_URL` |
| Stats stale after a write | — | Not expected; writes invalidate. Check Redis connectivity |
| 429s on every request | Bucket not refilling, or window/burst misconfigured | Confirm `RATE_LIMIT_WINDOW` and `RATE_LIMIT_BURST` are positive |
| 429 with no `Retry-After` | Regression — header must always be set on 429 | Check `backend/app/routes/complaints.py:151-157` |
| Rate limit not applying across replicas | Each replica using its own local counter | Confirm both replicas share `REDIS_URL` |
| Redis down, app returns 500 | `RATE_LIMIT_FAIL_CLOSED=true` plus unreachable Redis | Set `false` for availability-first, or restore Redis |
| `connection pool exhausted` | Too few connections for replica count | Raise the pool size in `backend/app/providers/cache.py` |

---

## 5. Deployment

*Owner: Jibran. Kustomize base + dev/prod overlays, deployed by `cd.yml`.*

### A. Local Development (Docker Compose)
```bash
# Start the full stack (postgres, redis, ollama, migrate, backend, frontend)
docker compose up -d

# Verify readiness of all services
curl http://localhost:8000/ready
```

### B. Kubernetes (k3d / Production Cluster)

```bash
# Create the cluster (if not already running)
k3d cluster create civicpulse

# Apply kustomize overlay for production
kubectl apply -k k8s/overlays/prod

# Verify pod status and rollout progress
kubectl rollout status deployment/backend -n civicpulse
kubectl get pods -n civicpulse
```

Validate the manifests before applying anything:

```bash
# Render exactly what will be applied, and confirm the object count
kustomize build k8s/overlays/prod | tee /tmp/rendered.yaml | grep -c '^kind:'

# Schema validation against the live API server
kubeconform -strict -ignore-missing-schemas -summary /tmp/rendered.yaml
```

`k8s/overlays/prod/kustomization.yaml` sets `replicas: 2` for the backend
Deployment, which **must stay equal to the HPA's `minReplicas`**. The HPA owns
that field and reconciles toward `minReplicas`; a declarative value above it
produces a permanent fight between the overlay and the autoscaler.

`k8s/base/secret.yaml` ships the Postgres/Redis credentials as base64 `data`
(same values as `.env.example`), but **`GROQ_API_KEY` is intentionally empty** —
the real key is a GitHub secret and is never committed. CD patches the real key
into the Secret before applying, so a pipeline deploy always has it.

For a hand-run local cluster there is no pipeline, so triage falls back to the
rule-based provider on every request (counted as `triage_fallback_total`). To
use Groq locally:

```bash
kubectl -n civicpulse create secret generic civicpulse-secrets \
  --from-literal=POSTGRES_PASSWORD=postgres \
  --from-literal=DATABASE_URL='postgresql://postgres:postgres@postgres:5432/civicpulse' \
  --from-literal=REDIS_URL='redis://redis:6379/0' \
  --from-literal=GROQ_API_KEY='gsk_xxx' \
  --dry-run=client -o yaml | kubectl apply -f -
kubectl rollout restart deployment/backend -n civicpulse
```

The four `--from-literal` keys must match `k8s/base/secret.yaml`; the
`--dry-run=client | kubectl apply -f -` form makes the command idempotent.
`DATABASE_URL` embeds the password, so it has to be changed alongside
`POSTGRES_PASSWORD`.

> The Secret holds Postgres credentials in plaintext-equivalent base64, which is
> encoding, not encryption. RBAC is what protects it. See
> `docs/adr/0004-pii-and-data-governance.md`.

---

## 6. Rollback

*Owner: Jibran. Two mechanisms, both demonstrated on video.*

### A. Kubernetes Automated Rollback
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

### B. Git / Docker Compose Rollback
```bash
# Revert to the last known stable Git tag or commit
git checkout <previous-tag-or-commit-sha>

# Restart containers using immutable image digests
docker compose -f compose.prod.yaml up -d
```

### C. Database rollback

A code rollback does not roll back the schema. If the bad release carried a
migration:

```bash
cd backend
alembic current                        # what is applied now
alembic downgrade -1                   # back one revision
kubectl rollout restart deployment/backend -n civicpulse
```

> Rolling the Deployment back while a forward migration is still applied is the
> failure mode to avoid — the old code will query a schema it does not expect.
> Downgrade first, then roll back the code.

### D. Identifying what is actually running

Because images deploy by immutable digest, the running version is always
answerable in one command:

```bash
# The digest the pod is running
kubectl get pods -n civicpulse -o jsonpath='{.items[*].spec.containers[*].image}'

# Which git commit built that digest
git log -1 --format='%H %s' <digest>
```

---

## 7. Logging & Metrics

*Owner: Jibran. Structured JSON logs + Prometheus metrics.*

### 7.1 Logs

The backend emits **structured JSON**, one object per line, each carrying a
`request_id` that correlates every line belonging to a single request.

```bash
# A. Docker Compose
docker compose logs -f -t                      # everything, timestamped
docker compose logs -f backend                 # backend only
docker compose logs -f redis
docker compose logs -f postgres

# B. Kubernetes
kubectl logs -l app=backend -n civicpulse -f --tail=100   # all replicas
kubectl logs -l app=backend -n civicpulse | grep "triage_fallback"

# Every log line for one request
kubectl logs -l app=backend -n civicpulse | grep '<request_id>'

# Logs from a single pod, including ones that have since restarted
kubectl logs <pod-name> -n civicpulse --previous
```

### 7.2 Metrics

```bash
curl http://localhost:8000/metrics
```

| Metric | Type | Labels | Purpose |
|---|---|---|---|
| `http_requests_total` | Counter | `method`, `endpoint`, `status` | Requests handled, by route template |
| `http_request_duration_seconds` | Histogram | `method`, `endpoint` | End-to-end request latency |
| `triage_duration_seconds` | Histogram | — | Triage latency incl. cache lookup and fallback |
| `triage_total` | Counter | `provider`, `outcome` | Outcomes are `cached` or `live`, so a cache hit is distinguishable from real inference |
| `triage_fallback_total` | Counter | `provider` | Fallbacks, labelled by originating provider |

```bash
# Live fallback rate by provider
curl -s http://localhost:8000/metrics | grep '^triage_fallback_total'

# p95 triage latency
curl -s http://localhost:8000/metrics | \
  grep '^triage_duration_seconds_bucket' | awk '$2+0 >= 0.5 {print $2}' | tail -1
```

Both histograms use custom buckets up to **10 s**
(`backend/app/core/metrics.py:21`). The Prometheus default set stops at 10 s,
which would collapse every slow model call into `+Inf` and make the histogram
useless for exactly the requests you most need to look at.

### 7.3 Health endpoints

| Endpoint | Meaning | Use for |
|---|---|---|
| `/health` | Process is alive | Liveness probe |
| `/ready` | DB and Redis reachable | Readiness probe |
| `/metrics` | Prometheus exposition | Scraping |

`/ready` returning 503 means the pod is running but must not receive traffic —
K8s will hold it out of the Service endpoints until dependencies recover.

```bash
# In-cluster
kubectl -n civicpulse exec deploy/backend -- curl -s localhost:8000/ready

# Which endpoint a failing probe is hitting
kubectl describe pod <pod> -n civicpulse | grep -A3 "Readiness"
```

### 7.4 HPA observability

```bash
# Watch the autoscaler react
kubectl get hpa -n civicpulse -w

# Current vs desired — divergence means the HPA is mid-decision
kubectl get hpa backend -n civicpulse \
  -o jsonpath='{.status.currentReplicas} current / {.status.desiredReplicas} desired{"\n"}'

# Per-pod CPU, the input the HPA actually reads
kubectl top pods -n civicpulse -l app=backend

# The configured behaviour, for reference
kubectl get hpa backend -n civicpulse -o yaml
```

The HPA scales on **CPU utilization against the pod's `requests`**, not
absolute CPU. `k8s/base/backend.yaml` sets `requests.cpu: 500m`, so 60%
utilization means ~300 m of actual usage per pod. If `requests.cpu` is ever
removed, utilization becomes meaningless and the HPA will not scale.

---

## 8. CI/CD Pipelines

*Owner: Jibran. Three GitHub Actions workflows.*

| Workflow | Trigger | Job |
|---|---|---|
| `ci.yml` | Every push and PR | Lint, typecheck, test, Trivy, kubeconform, build, compose smoke |
| `cd.yml` | Push to `dev` / `main`, and reusable | Build to GHCR by SHA, deploy to k3d, smoke test |
| `release.yml` | Semver tag (`v*`) | Tagged build for the release artifact |

### A. The gate

`cd.yml` calls `ci.yml` through `uses: ./.github/workflows/ci.yml` and depends
on it with `needs:`. No image is published and nothing is deployed unless CI
passed first.

### B. Deploy-by-digest

Images are **never deployed by tag**. The build step reports each image's
content digest, CD writes it into the Kustomize overlay as
`repo@sha256:...`, and a guard greps the rendered manifest to confirm the digest
actually landed before applying.

```bash
# Which SHA is production running?
git log -1 --format='%H'          # answer is one word, pasteable
```

Rationale and consequences: `docs/adr/0003-deploy-by-sha.md`.

### C. Required GitHub secrets

| Secret | Used by | Notes |
|---|---|---|
| `GHCR_TOKEN` | `cd.yml`, `release.yml` | Classic PAT, `write:packages`, scoped and revocable |
| `GHCR_USERNAME` | `cd.yml`, `release.yml` | Push identity |
| `GROQ_API_KEY` | `cd.yml` | Patched into the Secret at deploy time; **never committed** |

### D. Re-running a pipeline

```bash
gh run list --workflow=cd.yml --limit=5
gh run view <run-id> --log-failed
gh run rerun <run-id> --failed
```

If a deploy failed **after** the image was pushed, re-run is safe — the digest
is already in GHCR and is immutable.

### E. Local pre-flight

Run what CI runs before opening a PR:

```bash
# Lint and typecheck
cd backend && ruff check . && mypy app
cd frontend && npm run lint && npm run build

# Tests
cd backend && pytest --cov=app
cd frontend && npm test

# Manifest validation
kustomize build k8s/overlays/prod | kubeconform -strict -ignore-missing-schemas -

# Confirm nothing was pushed by tag
kustomize build k8s/overlays/prod | grep -E '^\s*image:' | grep -v '@sha256:' && \
  echo "FAIL: a tag-based image reference is present"
```

---

## 9. Troubleshooting Matrix

*Joint. Start here for any incident, then jump to the owning section.*

| Symptom | Likely section | First command |
|---|---|---|
| Site returns 502/503 | §5, §7.3 | `kubectl get pods -n civicpulse` |
| `/ready` is 503 | §3, §7.3 | `kubectl -n civicpulse exec deploy/backend -- curl -s localhost:8000/ready` |
| Complaint not saved | §3 | `alembic current` |
| Database empty in dashboard | §3 | `python scripts/seed.py` |
| `X-Cache: MISS` every time | §4.1 | `redis-cli PING` |
| 429 on every request | §4.2 | `curl -i .../api/complaints?limit=1` |
| 429 with no `Retry-After` | §4.2 | Check `backend/app/routes/complaints.py:151-157` |
| Redis errors in logs | §4.3 | `redis-cli INFO memory` |
| Triage always `rules:fallback` | §9.1 below | `curl http://localhost:8000/api/meta/providers` |
| `GROQ_API_KEY is not configured` | §1, §9.1 | Set in `.env` or use `TRIAGE_PROVIDER=simulated` |
| HPA not scaling | §7.4 | `kubectl top pods -n civicpulse -l app=backend` |
| Pods `CrashLoopBackOff` | §7.3 | `kubectl logs <pod> -n civicpulse --previous` |
| Pods `ImagePullBackOff` | §5 | `kubectl describe pod <pod> -n civicpulse` |
| Frontend blank | §2 | `npm run build` and check `frontend/nginx.conf` |
| Frontend can't reach API | §2 | nginx proxies `/api`; check `frontend/nginx.conf` |

### 9.1 When triage fails

*Owner: Alishba. Provider fallback is the designed failure path, not an
incident — the complaint is still saved and triaged deterministically.*

1. **Confirm the fallback happened**:
   ```bash
   curl http://localhost:8000/api/meta/providers
   ```
   In `recent_outcomes`, `fallback: true` with `provider: "rules:fallback"` means
   the system is operating correctly on the local heuristic engine. No data is
   lost and the complaint is stored with `triaged_by="rules:fallback"`.

2. **Read the error class from the structured log**:
   ```json
   {"event": "triage_fallback", "complaint_id": "...", "provider": "llm:groq", "error_class": "HTTPStatusError"}
   ```
   - **`HTTPStatusError (401/403)`** — invalid or expired `GROQ_API_KEY`. Update
     in `.env` or the Kubernetes Secret.
   - **`HTTPStatusError (429)`** — Groq rate limit. The service uses the Redis
     content-hash cache first, then falls back to rules.
   - **`TimeoutException`** — exceeded `TRIAGE_TIMEOUT` (10 s). Check egress
     connectivity.
   - **`ValidationError`** — provider returned malformed output. `TriageResult`
     validation rejected it; this is the guardrail working.

3. **Switch to offline Ollama** if the cloud provider is down:
   ```bash
   # In .env or the Kubernetes ConfigMap:
   TRIAGE_PROVIDER=ollama
   ```
   ```bash
   docker compose restart backend          # local
   kubectl rollout restart deployment/backend -n civicpulse   # in-cluster
   ```

4. **Confirm recovery**:
   ```bash
   curl http://localhost:8000/api/meta/providers   # provider should read "ollama" or "llm:groq"
   kubectl get hpa backend -n civicpulse            # unchanged; triage latency is not the HPA metric
   ```

