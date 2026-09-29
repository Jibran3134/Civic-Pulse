# CivicPulse — Resilient Municipal Complaint Platform

[![CI Pipeline](https://github.com/Jibran3134/Civic-Pulse/actions/workflows/ci.yml/badge.svg)](https://github.com/Jibran3134/Civic-Pulse/actions/workflows/ci.yml)
[![CD Pipeline](https://github.com/Jibran3134/Civic-Pulse/actions/workflows/cd.yml/badge.svg)](https://github.com/Jibran3134/Civic-Pulse/actions/workflows/cd.yml)
[![Docker Hub](https://img.shields.io/badge/docker-multi--stage-blue.svg)](https://github.com/Jibran3134/Civic-Pulse)
[![License: MIT](https://img.shields.io/badge/License-MIT-yellow.svg)](https://opensource.org/licenses/MIT)
[![Python 3.12](https://img.shields.io/badge/python-3.12-blue.svg)](https://www.python.org/downloads/)
[![FastAPI](https://img.shields.io/badge/FastAPI-0.115+-009688.svg)](https://fastapi.tiangolo.com)
[![React 18](https://img.shields.io/badge/React-18-61dafb.svg)](https://react.dev)

> An enterprise-grade, cloud-native civic grievance intake platform with a resilient, pluggable AI triage pipeline.

## Table of Contents

1. [Overview](#1-overview)
2. [Architecture](#2-architecture)
3. [Quickstart](#3-quickstart)
4. [API Reference](#4-api-reference)
5. [Architectural Decision Records](#5-architectural-decision-records)
6. [Testing](#6-testing)
7. [Team](#7-team)
8. [License](#8-license)

---

## 1. Overview

### The Problem

Municipal complaint intake systems in developing metropolitan areas suffer from chronic operational failure modes:

| # | Problem | Impact |
|---|---|---|
| 1 | **Third-party outages & rate limits** | Relying purely on external cloud LLM providers causes system-wide 500 errors on `429` responses or provider outages. |
| 2 | **Citizen privacy leaks** | Unsanitized complaints send PII (phone numbers, CNIC, email) to third-party cloud models. |
| 3 | **Flaky, non-deterministic CI/CD** | Testing against live probabilistic models causes high latency, flaky builds, and quota depletion. |
| 4 | **Slow diagnostics** | Operators cannot tell whether a classification came from a cache, a cloud LLM, or a local fallback engine. |

### The Solution

**CivicPulse** is built with **FastAPI, React 18, PostgreSQL 16, and Redis 7**. It implements a resilient 4-layer architecture with:

- **Pluggable AI triage pipeline** — swap between Groq, Ollama, rules, and simulated providers
- **Automatic PII redaction** before any third-party dispatch
- **Prompt injection defense**
- **Redis content-hash caching** (24h TTL)
- **Seamless deterministic fallback** to a local rule engine
- **Provider transparency** — every result records who triaged it (`cache`, `rules:fallback`, etc.)

### Tech Stack

| Layer | Technology |
|---|---|
| Frontend | React 18 (TypeScript), served via Nginx |
| Backend | Python 3.12, FastAPI |
| Database | PostgreSQL 16 |
| Cache / Rate limiting | Redis 7 |
| AI providers | Groq (`llama-3.1-8b-instant`), Ollama (`llama3.2:1b`), rule-based engine, simulated mock |
| Infrastructure | Docker Compose, Kubernetes, GitHub Actions CI/CD |

---

## 2. Architecture

```mermaid
flowchart TD
    User([Citizen / Frontend]) -->|POST /api/complaints| NGINX[Nginx Reverse Proxy :80]
    NGINX -->|Forward /api| Backend[FastAPI Backend :8000]

    subgraph Service Layer
        Backend --> RateLimit{Redis Token Bucket<br/>Rate Limiter}
        RateLimit -- Exceeded --> Ret429[HTTP 429 Too Many Requests]
        RateLimit -- Allowed --> TriageService[TriageService Orchestrator]
    end

    subgraph Caching & Persistence
        TriageService --> CacheCheck{Redis Content Hash<br/>Cache (24h TTL)}
        CacheCheck -- Hit (~1ms) --> ReturnCache[Return Cached Result<br/>triaged_by = 'cache']
        CacheCheck -- Miss --> ActiveProvider[Invoke Active TriageProvider]
        Backend --> Postgres[(PostgreSQL 16 DB)]
    end

    subgraph Pluggable AI Triage Layer
        ActiveProvider --> Choice{Provider Selection}
        Choice -- llm:groq --> PIIScrub[PII Redaction & Guardrails]
        PIIScrub --> GroqCloud[Cloud Groq API<br/>llama-3.1-8b-instant]
        Choice -- llm:ollama --> OllamaContainer[Local Ollama SLM<br/>llama3.2:1b Container]
        Choice -- simulated --> MockEngine[Simulated Deterministic Mock]

        GroqCloud -- 429 / Outage / Timeout --> FallbackTrigger[Catch Exception<br/>Log Warning]
        OllamaContainer -- Failure --> FallbackTrigger
        FallbackTrigger --> RuleEngine[RuleBasedTriage Engine<br/>Local Municipal Keywords]
        RuleEngine --> PersistFallback[triaged_by = 'rules:fallback']
    end

    ReturnCache --> Postgres
    PersistFallback --> Postgres
    GroqCloud -- Valid JSON --> Postgres
    Postgres --> HTTPResponse[HTTP 201 Created Response]
    HTTPResponse --> User
```

### Request Lifecycle

1. **Ingress** — The citizen's `POST /api/complaints` reaches Nginx (`:80`), which forwards `/api` to the FastAPI backend (`:8000`).
2. **Rate limiting** — A Redis token bucket either allows the request or returns `429 Too Many Requests`.
3. **Cache check** — `TriageService` looks up the complaint's content hash in Redis. A hit (~1ms) returns the cached result with `triaged_by = 'cache'`.
4. **Provider selection** — On a miss, the active provider is invoked:
   - `llm:groq` — PII is redacted and guardrails applied, then the Groq cloud API is called.
   - `llm:ollama` — a local SLM container handles the request.
   - `simulated` — a deterministic mock, used for tests.
5. **Fallback** — Any Groq/Ollama failure (429, outage, timeout) is caught and logged, and the local `RuleBasedTriage` engine takes over with `triaged_by = 'rules:fallback'`.
6. **Persistence & response** — The result is stored in PostgreSQL and returned as `201 Created`.

---

## 3. Quickstart

CivicPulse ships a pre-configured, multi-network Docker Compose setup that brings up the full stack in one command.

### Prerequisites

- Docker Desktop & Docker Compose v2+
- Git

### Launch

```powershell
# Clone the repository
git clone https://github.com/Jibran3134/Civic-Pulse.git
cd Civic-Pulse

# Run the complete stack (Postgres, Redis, Backend, Frontend, Ollama)
docker compose up -d
```

### Services & Ports

| Service | URL / Port | Notes |
|---|---|---|
| **Frontend Portal** | [http://localhost:3000](http://localhost:3000) | Citizen submission & operational dashboard |
| **Backend API (Swagger)** | [http://localhost:8000/docs](http://localhost:8000/docs) | Interactive OpenAPI documentation |
| **Readiness Check** | [http://localhost:8000/ready](http://localhost:8000/ready) | Verifies PostgreSQL and Redis health |
| **PostgreSQL 16** | `localhost:5432` | User: `postgres`, DB: `civicpulse` |
| **Redis 7** | `localhost:6379` | Token bucket limiter & content cache |
| **Ollama SLM** | `http://localhost:11434` | Local model `llama3.2:1b` |

---

## 4. API Reference

CivicPulse exposes 10 standardized REST endpoints conforming to the project API contract.

### Complaints

| Method | Endpoint | Description | Notes | Status Codes |
|---|---|---|---|---|
| `POST` | `/api/complaints` | Ingest complaint; PII redaction & AI triage | Writes to DB, invalidates stats cache | `201`, `400` |
| `GET` | `/api/complaints` | Paginated listing with filters | Params: `page`, `page_size`, `category`, `status` | `200`, `400` |
| `GET` | `/api/complaints/{id}` | Retrieve complaint by UUID | — | `200`, `404`, `400` |
| `PATCH` | `/api/complaints/{id}/status` | Update status via state machine | Strict transition table | `200`, `400`, `409` |

### Insights

| Method | Endpoint | Description | Notes | Status Codes |
|---|---|---|---|---|
| `GET` | `/api/stats` | Aggregated metrics by category and priority | Cached 30s (`X-Cache: HIT/MISS`) | `200` |
| `GET` | `/api/meta/providers` | Active triage provider & last 20 outcomes | Reads Redis ring buffer | `200` |

### Health & Observability

| Method | Endpoint | Description | Notes | Status Codes |
|---|---|---|---|---|
| `GET` | `/health` | Liveness probe (does not touch DB/Redis) | K8s liveness probe | `200` |
| `GET` | `/ready` | Readiness probe (verifies DB & Redis) | K8s readiness probe | `200`, `503` |
| `GET` | `/metrics` | Prometheus telemetry (triage latency, fallbacks) | Scraped by Prometheus / VictoriaMetrics | `200` |
| `GET` | `/healthz` | Frontend Nginx health check | Returns `200 ok` | `200` |

---

## 5. Architectural Decision Records

Key decisions are preserved in [`docs/adr/`](docs/adr/):

| ADR | Decision |
|---|---|
| [0001 — Pluggable TriageProvider Interface](docs/adr/0001-provider-interface.md) | A `typing.Protocol` interface decouples business logic from Groq, Ollama, Rules, and Simulated providers. |
| [0002 — Frontend Runtime Configuration](docs/adr/0002-frontend-runtime-config.md) | Build-once-deploy-many: Nginx reverse-proxies `/api`, so no URLs are baked into the build. |
| [0003 — Immutable Deployment by Digest SHA](docs/adr/0003-deploy-by-sha.md) | Immutable `@sha256:` image digests in CI/CD and K8s give byte-for-byte reproducibility. |
| [0004 — PII Redaction & Data Governance](docs/adr/0004-pii-and-data-governance.md) | Phone numbers, CNICs, and emails are sanitized before any third-party LLM dispatch. |

---

## 6. Testing

```powershell
# Backend: 38 unit & contract tests
cd backend
pytest tests/test_triage.py tests/test_ollama.py -v

# Frontend: 7 Vitest component tests
cd ../frontend
npm test
```

---

## 7. Team

| Contributor | Responsibilities |
|---|---|
| **Muhammad Jibran** | Backend, infrastructure, PostgreSQL migrations, Redis rate limiter, Kubernetes manifests, CI/CD pipelines |
| **Alishba Nasir** | React 18 TypeScript frontend, pluggable AI layer, PII guardrails, prompt injection defenses, ADR documentation |

---

## 8. License

Released under the [MIT License](https://opensource.org/licenses/MIT).
