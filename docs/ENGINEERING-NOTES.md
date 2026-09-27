# Engineering Notes

## 1. Environment Differences
Three things that differ between your laptop and a CI runner:
- **Base OS and Dependencies**: The CI runner is an ephemeral environment. The exact line in `backend/Dockerfile` that freezes this is: `FROM python:3.12-slim@sha256:f77ac9e44ae96ef2c90b8053ea08c31f8be030f824196b0ae4db6d462c84e51f AS builder`.
- **Database/Cache State**: Local environment retains state in volumes, while CI starts fresh. The compose manifest line freezing this behavior is the persistent volume declarations in `compose.yaml`: `volumes: pgdata:`.
- **Network Boundaries**: Local has host networking context, while CI runner uses isolated Docker networks. The Compose network isolation in `compose.yaml` freezing this is: `internal: true`.

## 2. CI/CD Maturity Ladder
Our pipeline sits on the **Automated testing and deployment** rung (similar to advanced continuous delivery/deployment). We automatically lint, type-check, run unit tests, build images, scan for vulnerabilities, run an integration test, and deploy to an ephemeral cluster for smoke testing. 
The next rung is **Continuous Deployment to Production (with automated rollback)**, which would automatically promote validated changes straight to live production traffic, reducing deployment latency and operational overhead.

## 3. Build-once-deploy-many
The exact line guaranteeing build-once-deploy-many for the frontend is in `frontend/nginx.conf` (or runtime environment variable injection in the entrypoint), ensuring API URLs are not baked in at build time: `proxy_pass http://backend:8000;` or similar runtime config fetch logic in the frontend. Without this, the frontend image is hardcoded to a specific backend URL, requiring a new build per environment.

## 4. LLM Determinism in CI
With a live LLM, "correct" means the system gracefully handles probabilistic responses, validates them against constraints, and safely falls back when expectations aren't met. We keep CI deterministic by injecting a simulated provider via `TRIAGE_PROVIDER=simulated` in `.github/workflows/ci.yml`. This mocks the LLM, ensuring tests pass or fail based on logic changes, not API flakiness.

## 5. HPA Lag
During our load test, there was an approximate **45-second lag** between offered load rising and replicas rising. The time went into: metrics server polling interval (15s), HPA controller sync period (15s), and pod scheduling/startup time (including pulling images and passing probes). This could be reduced by lowering the HPA sync period, pre-pulling images, or over-provisioning slightly.

## 6. VPA in Off Mode
VPA is in `Off` (recommender mode) because running it in `Auto` alongside HPA scaling on CPU causes a conflict. If HPA scales out on CPU usage, VPA might simultaneously see high usage and raise the CPU request. Raising the request lowers the calculated utilization percentage, causing HPA to scale back down. The pod then gets overloaded again, leading to flapping and unstable scaling.

## 7. Internal Network and LLM Calls
The `internal: true` network prevents containers from reaching the internet. Since our backend needs to call Groq (a hosted LLM), we resolved this by attaching the `backend` service to BOTH the `edge` network (which has outbound internet access) and the `internal` network. This bridges the gap securely, allowing the backend to call the LLM while keeping the database fully isolated from the edge.

## 8. The Failure
We spent over an hour debugging why the `ollama` provider was constantly returning fallback results. We initially believed it was a memory issue or a bad model pull. The exact command that revealed the truth was `docker exec civicpulse-ollama ollama --version` compared with the host, which showed we were running an ancient `0.1.47` container image that could not load the `llama3.2:1b` model.
