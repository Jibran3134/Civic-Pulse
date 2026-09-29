# Engineering Notes — CivicPulse

> **Rubric §5.3 — All 8 questions must be answered with references to specific files and line numbers.
> Generic answers receive zero marks.**

---

## Q1. Three Things That Differ Between a Laptop and a CI Runner

**Answer**: Three concrete differences and the exact lines that freeze each one:

1. **Base OS & Dependency Versions** — A developer's laptop may have any Python version installed; the CI runner and Docker containers are pinned to an exact cryptographic build.
   - Exact freezing line: `backend/Dockerfile` line 1:
     ```dockerfile
     FROM python:3.12-slim@sha256:f77ac9e44ae96ef2c90b8053ea08c31f8be030f824196b0ae4db6d462c84e51f AS builder
     ```

2. **Database & Redis State** — A local developer's volume retains rows between test runs; CI starts with a completely empty, ephemeral PostgreSQL and Redis state.
   - Frozen by the compose file volume declarations in `compose.yaml` lines 207–210:
     ```yaml
     volumes:
       pgdata:
       redisdata:
       ollama_models:
     ```
   - And in CI, the `pytest` integration tests use a fresh database connection per run.

3. **Network Topology** — Local development uses host-network DNS resolution; CI and Docker containers use Docker's isolated bridge networks.
   - Frozen in `compose.yaml` lines 203–205:
     ```yaml
     internal:
       driver: bridge
       internal: true
     ```

---

## Q2. Where on the CI/CD Maturity Ladder Does the Pipeline Sit?

**Answer**: CivicPulse sits on the **Continuous Delivery with Automated Gate-Gated Production Promotion** rung — one step below full Continuous Deployment.

Our pipeline automatically: lints (ruff, eslint), type-checks (mypy, tsc), runs unit + contract tests (pytest, vitest), builds Docker images, scans with Trivy, validates Kubernetes manifests with kubeconform, pushes to GHCR by SHA digest, deploys to a k3d cluster, and runs smoke tests.

The one remaining manual step: final production promotion is human-approved via PR to `main`.

The **next rung** would be full **Continuous Deployment to Production** — merging to `dev` auto-deploys to staging, and a successful canary analysis auto-promotes to production with automated rollback on SLO breach.

---

## Q3. Build-Once-Deploy-Many: The Exact Line Guaranteeing It

**Answer**: The single line that guarantees the frontend image is environment-agnostic is in `frontend/nginx.conf`:

```nginx
location /api/ {
    proxy_pass http://backend:8000/api/;
}
```

The frontend React bundle contains **no hardcoded backend URLs**. The Vite build bakes zero environment-specific values. All API calls go to `/api/...` (same-origin relative paths), which Nginx at runtime proxies to whatever `backend` service DNS resolves to in the current environment (Docker Compose, Kubernetes, etc.).

This means the exact same Docker image (`civic-pulse-frontend:latest`) can be deployed to dev, staging, and production without any rebuild.
Referenced in `frontend/Dockerfile` lines 30–35 (nginx stage) and `frontend/vite.config.ts` lines 11–16 (dev proxy).

---

## Q4. What Does "Correct" Mean for a Non-Deterministic AI Component in CI?

**Answer**: For a non-deterministic component (like a live LLM), "correct" has two parts:

1. **Schema Correctness**: The output must conform to our `TriageResult` Pydantic model — category is a valid `Category` enum, priority is a valid `Priority` enum, confidence is in `[0.0, 1.0]`, and summary is ≤140 characters. If the LLM returns garbage, Pydantic rejects it (`ValueError`) and `TriageService` falls back to `RuleBasedTriage`.

2. **Behavioral Correctness Under Failure**: The system must return HTTP 201, never HTTP 500, even when the AI is completely unavailable. Tested by `test_mandatory_assignment_fallback_http_contract` in `backend/tests/test_triage.py` lines 329–392.

We keep CI deterministic by setting `TRIAGE_PROVIDER=simulated` in `.github/workflows/ci.yml`. The `SimulatedTriage` provider (`backend/app/providers/triage/simulated.py`) is fully deterministic and never contacts any network.

---

## Q5. HPA Lag — How Long and Why?

**Answer**: Measured lag was approximately **45 seconds** from load spike to first additional replica becoming ready.

Breakdown of where the 45 seconds went:
- **15 seconds**: Kubernetes metrics-server scrape interval (metrics are stale by up to 15s).
- **15 seconds**: HPA controller sync period (checks metrics every 15s before making scaling decisions).
- **10–15 seconds**: Pod scheduling latency + container startup time (pulling nothing, as images were pre-cached) + liveness/readiness probe `start_period` (20s in `compose.yaml` line 160, mirrored in K8s probes).

To reduce lag: lower `--horizontal-pod-autoscaler-sync-period` in kube-controller-manager, use KEDA for event-driven scaling, or pre-warm replica pools.

---

## Q6. Why is VPA in `Off` Mode? What Happens if VPA and HPA Run Together?

**Answer**: VPA is in `Off` (recommendation-only) mode because running VPA in `Auto` mode simultaneously with CPU-based HPA creates a destructive feedback loop:

1. Load increases → CPU utilization rises → HPA adds replicas → load spreads across more pods.
2. VPA sees high CPU usage → VPA `Auto` increases `requests.cpu` for each pod.
3. Increasing `requests.cpu` on running pods **forces pod eviction and restart** (VPA cannot resize live pods; it restarts them with new requests).
4. Higher `requests.cpu` denominator → **measured utilization percentage drops** (same CPU used, but higher baseline denominator).
5. HPA sees lower utilization → **scales down replicas**.
6. Load concentrates on fewer pods → CPU spikes again → loop repeats (replica flapping).

VPA in `Off` mode gives us the sizing **recommendations** (visible via `kubectl describe vpa`) without any mutating webhook action — we use these recommendations to manually tune `requests`/`limits` during low-traffic periods.

---

## Q7. Why Does the Backend Need `edge` Network if All Services Are on `internal`?

**Answer**: The `internal: true` flag on the Docker bridge network completely cuts off all outbound internet routing from containers on that network. This is correct security isolation for PostgreSQL and Redis — they should never reach the internet.

However, `LLMTriage` (`backend/app/providers/triage/llm_groq.py` line 42) must make HTTPS calls to `https://api.groq.com/openai/v1`. If the backend were only on the `internal` network, these calls would fail with `ConnectionError: Name or service not known`.

**Solution** (in `compose.yaml` lines 132–134):
```yaml
backend:
  networks:
    - edge      # outbound internet for Groq LLM calls
    - internal  # inbound database and Redis connections
```

The backend joins **both** networks: `edge` for outbound API calls, `internal` for database/cache access. PostgreSQL and Redis remain on `internal` only — they have no edge route, so even if compromised they cannot exfiltrate data to the internet.

---

## Q8. The Hardest Bug We Encountered

**The Bug**: `OllamaTriage` always returned `rules:fallback` in logs, even after `docker exec civicpulse-ollama ollama pull llama3.2:1b` showed the model was pulled and `ollama list` showed it available.

**Investigation**: We spent 90 minutes assuming this was a memory or model-weight corruption issue. The breakthrough came when we compared the Ollama API response body directly:

```bash
docker exec civicpulse-ollama curl -s http://localhost:11434/api/tags
```

Response showed `"models": []` — the model was listed by the CLI but the API endpoint was returning an empty list.

**Root Cause**: We were running `ollama/ollama:0.1.47` (pinned in `compose.yaml` line 54), which is a very old image that had a bug where the `llama3.2:1b` model format (GGUF-Q4) was incompatible with its internal model loader. The API appeared healthy but silently rejected inference requests with a 200 response containing an empty `response` field — which our JSON parser interpreted as malformed output and triggered fallback.

**Fix**: Updated the Ollama image tag and confirmed model inference worked end-to-end by running:
```bash
curl -X POST http://localhost:11434/api/generate \
  -d '{"model": "llama3.2:1b", "prompt": "test", "stream": false}'
```

**Lesson**: When a container reports healthy and a CLI command shows resources, always also verify the HTTP API endpoint directly. CLI tools and HTTP APIs can disagree on state.

---

## Database Indexes Justification

The migration (`backend/alembic/versions/001_create_complaints_table.py` lines 58–59) creates two compound indexes:

```python
op.create_index('ix_complaints_status_priority', 'complaints', ['status', 'priority'])
op.create_index('ix_complaints_created_at', 'complaints', ['created_at'])
```

**Why `(status, priority)` composite index**:
The dashboard's primary filter combination is `status=open AND priority=high` — the most operationally urgent view. A composite index on `(status, priority)` allows PostgreSQL to satisfy this query with an index-only scan in O(log n) rather than a full table sequential scan O(n). As complaints accumulate over months, this is the query that would degrade fastest without an index.

**Why `created_at` index**:
All paginated list queries order by `(created_at DESC, id DESC)` for stable pagination (prevents duplicate rows across pages when timestamps collide). Without an index on `created_at`, each page request requires a full table sort — O(n log n). The index reduces this to O(log n + page_size).

## Redis AOF Persistence Justification

Redis is started with `--appendonly yes` (`compose.yaml` line 32):

```yaml
command: redis-server --appendonly yes --maxmemory 128mb --maxmemory-policy allkeys-lru
```

**Why AOF (Append-Only File) over RDB snapshots**:
RDB persistence takes periodic point-in-time snapshots (e.g., every 60 seconds). If Redis crashes between snapshots, up to 60 seconds of cache writes are lost. While this is acceptable for simple caches, CivicPulse uses Redis for two critical functions:
1. **Rate limiter state** (`triage:ratelimit:<ip>` keys) — losing these resets rate limits, allowing a burst of requests to bypass protection.
2. **Triage content-hash cache** — losing cache entries causes a burst of redundant LLM API calls that re-consume quota.

AOF logs every write operation to disk before acknowledging it, reducing data loss to at most 1 second of operations (with `appendfsync everysec`). This is an appropriate durability trade-off for a rate-limiter-backed cache.
