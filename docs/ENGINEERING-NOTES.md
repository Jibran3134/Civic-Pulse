# Engineering Notes

---

## 1. AOF on a Named Volume — Why Does a Cache Need Persistence?

Redis is enabled with Append-Only File (AOF) persistence in both Compose and Kubernetes.

**In Compose** (`compose.yaml` line 37):
```yaml
command: redis-server --appendonly yes --maxmemory 128mb --maxmemory-policy allkeys-lru
```
It writes to the named volume declared at `compose.yaml` line 233:
```yaml
volumes:
  redisdata:
```

**In Kubernetes** (`k8s/base/redis.yaml` line 43):
```yaml
command: ["redis-server", "--appendonly", "yes", "--maxmemory", "128mb", "--maxmemory-policy", "allkeys-lru"]
```
Backed by a PVC (`k8s/base/redis.yaml` lines 1-12).

**The question: why does a cache need a volume?**

The cache stores two kinds of state: stats aggregates (TTL 30 s, cheap to rebuild) and rate-limit token buckets (stateful, expensive to lose). If Redis restarts and forgets the token buckets, every client instantly gets a fresh bucket — a caller who was already at their limit can immediately exceed the LLM quota again right after a rollout. The AOF file survives a pod restart and replays those buckets within seconds. The cost is a small write-ahead log on disk; the benefit is that a container crash cannot be weaponised into a rate-limit bypass.

The defensible counter-argument — no volume, let buckets reset — is valid only if the rate limit is purely advisory and the LLM provider has its own hard quota. We chose persistence because the application enforces the limit itself and a reset is a real bypass, not just a nuisance.

---

## 2. Network Trade-Off — `internal: true` vs. Hosted LLM Access

The `internal` network is declared with `internal: true` (`compose.yaml` lines 228-232):
```yaml
networks:
  internal:
    driver: bridge
    internal: true
```

This means **no container on `internal` can reach the internet**. That is the right choice for `postgres` and `redis` — they have no business calling external APIs.

The problem: `backend` must call Groq (a hosted LLM). If `backend` were placed only on `internal`, every `TRIAGE_PROVIDER=groq` request would time out.

**The resolution** is that `backend` joins **both networks** (`compose.yaml` lines 157-159):
```yaml
networks:
  - edge
  - internal
```

`edge` is a normal bridge (outbound internet allowed). `internal` gives the backend a route to `postgres` and `redis`. No other service joins both: `frontend` is edge-only, `postgres`/`redis` are internal-only, so the database is unreachable from the internet and from the frontend.

**The architecture this creates:**
```
[internet] <-> edge <-> frontend
                    <-> backend <-> internal <-> postgres
                                             <-> redis
                    <-> ollama (also on edge for model pulls)
```

An alternative defensible design would be a sidecar proxy or egress gateway that holds the Groq API key and routes all LLM traffic — keeping the backend on `internal` only. We chose the simpler two-network approach because the backend is the only service that holds the API key and the added complexity of a proxy is not justified at this scale.

---

## 3. `volumes: redisdata:` — Justification

**In Compose** (`compose.yaml` lines 233-235):
```yaml
volumes:
  redisdata:
```

**In Kubernetes** (`k8s/base/redis.yaml` lines 71-78):
```yaml
volumes:
  - name: redisdata
    persistentVolumeClaim:
      claimName: redisdata
```

An `emptyDir` would silently discard the AOF on every pod replacement. Redis is a Deployment (not a StatefulSet) because it holds no ordered per-replica identity, but it still needs a real PVC. Without this volume, a pod restart during a load spike resets all token buckets, hands every caller a fresh limit, and the backend can be forced to exhaust the LLM quota through an orchestrated sequence of restarts and bursts. The comment in `k8s/base/redis.yaml` line 74 states this explicitly: "an emptyDir here would silently discard the AOF on every pod replacement."

---

## 4. Autoscaling Lag and Capacity Planning

When load arrives, replicas do not. There is a chain of delays: the metrics server must scrape CPU usage (scrape interval ~15 s), the HPA controller must read those metrics and decide to scale (sync period ~15 s, `k8s/base/hpa.yaml` line 32 `periodSeconds: 15`), the scheduler must find a node with enough free CPU to place the new pod, the kubelet must pull the image and start the container, and the readiness probe must pass before traffic is routed. In our load test the total lag from offered-load rising to new replicas serving requests was approximately 45 seconds under best-case conditions.

This lag is why autoscaling is not a substitute for capacity planning: a sudden spike that lasts 45 seconds is already over before the first new pod is ready, and the existing replicas have been under full pressure the entire time. The right approach is to start from a baseline that can absorb the expected burst without scaling, and use autoscaling only for sustained growth that develops slowly enough for the lag to be acceptable. Noticing that the HPA reacted but the latency spike had already come and gone was the concrete observation that forced this conclusion.

---

## 5. Why VPA Runs in `Off` Mode

VPA is set to `updateMode: "Off"` (`k8s/base/vpa.yaml` line 12):
```yaml
updatePolicy:
  updateMode: "Off"  # Recommender only - never Auto.
```

If VPA ran in `Auto` mode alongside the HPA, the two controllers fight each other in a loop:

1. Load rises -> HPA scales out -> more pods -> per-pod CPU drops.
2. VPA sees lower per-pod CPU -> recommends lower CPU requests -> applies them by evicting and restarting pods.
3. Fewer CPU requests -> higher measured utilisation percentage -> HPA scales out again.
4. More pods -> lower per-pod CPU -> VPA recommends lower requests again.

The result is continuous pod evictions and replica count oscillation. In `Off` mode, VPA only generates recommendations visible in `kubectl describe vpa backend-vpa`. We read those recommendations to manually tune the `requests` in the deployment manifest, getting the sizing benefit without the instability. The comment in `k8s/base/vpa.yaml` lines 13-14 spells this out: "VPA raises CPU requests -> utilization drops -> HPA scales in -> per-pod load rises -> VPA raises requests again, in a loop."

---

## 6. Three Differences Between Laptop and CI Runner

| # | What differs | Where it is frozen |
|---|---|---|
| 1 | **Python interpreter and OS libraries** — laptop may have a different Python patch version, glibc, or OpenSSL than the CI runner | `backend/Dockerfile` line 2: `FROM python:3.12-slim@sha256:f77ac9e44ae96ef2c90b8053ea08c31f8be030f824196b0ae4db6d462c84e51f AS builder` — the SHA256 digest pins the exact image layer, not just the tag |
| 2 | **Persistent database/cache state** — laptop retains rows and Redis keys across runs; CI starts blank | `compose.yaml` line 233: `volumes: redisdata:` — CI tears down volumes with `docker compose down -v` after every run (`.github/workflows/ci.yml` line 510) |
| 3 | **Network topology** — laptop has host networking and can reach external services; CI uses isolated Docker bridge networks | `compose.yaml` lines 228-232: `internal: true` blocks all outbound traffic from `internal` services — which is why CI forces `TRIAGE_PROVIDER=simulated` (`.github/workflows/ci.yml` line 110) |

---

## 7. CI/CD Maturity Ladder

Our pipeline sits on the **Continuous Integration + Continuous Delivery** rung. Every commit is linted, type-checked, unit-tested, image-built, vulnerability-scanned with Trivy, and smoke-tested against a live Compose stack before merge. Deployment to a cluster is scripted and repeatable but requires a manual trigger (push to `main` via `cd.yml`).

The next rung is **Continuous Deployment** — every green commit on `main` promotes automatically to production with no human gate, plus automated rollback if post-deployment health checks fail. What that buys: deployment lead time collapses from hours (waiting for a human to approve) to minutes, and the feedback loop between a code change and real-world behaviour becomes near-instant.

---

## 8. Build-Once Deploy-Many

The exact guarantee is in `.github/workflows/ci.yml` line 279:
```yaml
tags: ${{ env.REGISTRY }}/${{ env.IMAGE_NAME }}-backend:${{ github.sha }}
```

The image is tagged with the **Git commit SHA** — a content-addressed, immutable identifier. The same SHA tag is what CD pulls and deploys to Kubernetes. The image built in CI is byte-for-byte what runs in production; no rebuild happens at deploy time.

Without this: CD would re-run `docker build`, which might produce a different image if a base layer was updated, a `pip install` pulled a newer dependency, or any non-pinned `apt` package changed. The image that passed security scanning would not be the image that runs in production, making the scan meaningless.

---

## 9. LLM Determinism in CI

With a live LLM provider, "correct" means the system handles probabilistic, variable-length responses gracefully: it validates the category against the allowed enum, falls back safely when the model returns garbage, and never surfaces a raw exception to the caller. The output is not a fixed string — it is a contract (valid category, valid provider label, HTTP 200).

CI is kept deterministic by injecting `TRIAGE_PROVIDER=simulated` (`.github/workflows/ci.yml` line 110):
```yaml
TRIAGE_PROVIDER: simulated
```

The simulated provider returns a fixed, rule-based response with no network call and no randomness. Integration tests assert the contract — category is one of the defined enum values, `triaged_by` is present (`.github/workflows/ci.yml` lines 466-467) — rather than a specific string. This means a test failure signals a logic regression, never an API timeout or a model mood.

---

## 10. HPA Lag

The HPA is configured at `k8s/base/hpa.yaml`. Scale-up policy: up to 100% more pods or 2 pods per 15 s window, whichever is larger (lines 30-36), with `stabilizationWindowSeconds: 0` on scale-up (line 28 — no delay before acting).

During our load test, the lag between offered load rising and new replicas serving traffic was approximately **45 seconds**. Time breakdown:

| Step | Approx. time |
|---|---|
| Metrics server scrape interval | ~15 s |
| HPA controller sync period | ~15 s |
| Pod scheduling + image pull (already cached) | ~5-10 s |
| Readiness probe to pass | ~5 s |

What would reduce it: lower the metrics scrape interval (adds Prometheus load), pre-scale before a known event (capacity planning), or use KEDA with a custom metric that reacts faster than CPU such as queue depth.

---

## 11. VPA in Off Mode — Failure Mode of Auto + HPA Together

See section 5 above. The specific failure mode: VPA in `Auto` evicts pods to apply new resource requests. Each eviction is a brief outage for that pod's in-flight requests. If HPA has just scaled out to handle load, VPA evicting those new pods mid-spike means the cluster is simultaneously trying to add capacity and destroying it. The net effect is higher latency during the exact period the user is experiencing degraded service, combined with constant pod churn that makes logs unreadable and metrics noisy.

---

## 12. `internal: true` and the Hosted LLM — Full Resolution

See section 2 above. Short version: `backend` joins `edge` (for Groq calls) and `internal` (for postgres/redis). `postgres` and `redis` join only `internal` and cannot reach the internet or the frontend. `ollama` joins both `internal` (so the backend can call it) and `edge` (so it can run `ollama pull` to download model weights — a container on `internal: true` has no route to `registry.ollama.ai`) as documented in `compose.yaml` lines 70-82.

---

## 13. The Failure — Ollama 0.1.47 and the Silent Fallback

**Symptom:** The `ollama` triage provider always returned rule-based results. The container reported healthy. No errors in the backend logs. Category assignments looked plausible.

**What we believed first:** Memory limit too low — the model was being evicted before inference completed. We raised the memory reservation and ran again. Same result.

**The truth:** The Ollama container was version `0.1.47`, which predates the `llama3.2` model and cannot parse its tensor layout. Every `/api/generate` call returned HTTP 500. The backend's `OllamaTriage` provider caught the 500, logged a warning, and silently fell back to the rule-based provider — the exact fallback path that is supposed to be an emergency measure was the only path ever used. The container still passed its healthcheck (`ollama list` exits 0 with zero loadable models).

**The exact log line that told the truth:**
```
wrong number of tensors; expected 147, got 146
```
Found by running:
```bash
docker logs civicpulse-ollama 2>&1 | grep tensor
```

**Fix:** Pin the image to a verified working version (`compose.yaml` line 68):
```yaml
image: ollama/ollama:0.34.4
```
And replace the healthcheck with one that actually runs inference (`compose.yaml` line 96):
```yaml
test: ["CMD", "ollama", "run", "llama3.2:1b", "ok"]
```
A bad model name or unloadable model now exits 1, making the container report unhealthy instead of silently falling back. This is documented in the comment block at `compose.yaml` lines 84-95.
