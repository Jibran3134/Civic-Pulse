# ADR 0002: Frontend Runtime Configuration via Nginx Reverse Proxy

* **Status**: Accepted
* **Date**: 2026-09-27
* **Authors**: Alishba, Jibran
* **Context**: CivicPulse Assignment CS4032 (§2.1 Frontend Layer)

---

## 1. Context and Problem Statement

A single-page application (SPA) compiled to static JavaScript and HTML must communicate with a dynamic backend API. In typical 12-factor cloud-native environments (Local development, Docker Compose, Kubernetes `dev`, and Kubernetes `prod`), backend endpoints change hostnames, internal DNS names, ports, and protocols.

Baking absolute API URLs (`http://localhost:8000`, `http://civicpulse-backend:8000`, or `https://api.civicpulse.org`) into JavaScript bundles at build time (`VITE_API_URL`) violates the principle of environment parity:
1. It forces a complete rebuild of the container image for every environment promotion.
2. It leaks internal infrastructure DNS topology into client-side code.
3. It exposes the frontend to Cross-Origin Resource Sharing (CORS) preflight latencies and configurations.

---

## 2. Decision Drivers

1. **Build Once, Deploy Anywhere**: The identical Docker image artifact built in CI must run unchanged across local Compose, kind/k3d development clusters, and production Kubernetes overlays.
2. **Eliminate Build-time Coupling**: Zero backend hostnames or ports baked into the compiled static JS bundle.
3. **CORS Elimination**: When browser requests to `/api` are served from the same origin as the static HTML, cross-origin security friction is eliminated.
4. **Simple Local DX**: Local Vite dev server must mirror the production reverse-proxy behavior transparently.
5. **No Secrets Leakage**: Under no circumstances should backend secrets or sensitive URLs be bundled into client assets.

---

## 3. Considered Options

1. **Option A: Build-time Environment Inlining (`VITE_API_URL`)**:
   * *Cons*: Rebuilding container images per environment, high maintenance, breaks parity.
2. **Option B: Runtime `/config.js` script injection**:
   * Generates a dynamic `config.js` via an entrypoint shell script inside the Nginx container at startup (`window.__CONFIG__ = { API_URL: ... }`).
   * *Cons*: Requires shell execution in runtime container, extra HTTP roundtrip for `config.js`, non-standard TypeScript typing.
3. **Option C: Nginx Reverse Proxy `/api` Route (Chosen)**:
   * The frontend code only ever requests relative paths: `/api/*`.
   * In development, Vite's internal development proxy forwards `/api` to `http://localhost:8000`.
   * In containerized environments (Docker Compose & Kubernetes), Nginx acts as an edge reverse proxy forwarding `location /api/` directly to `http://backend:8000/api/`.

---

## 4. Decision Outcome

We choose **Option C: Nginx Reverse Proxy `/api` Route**.

### Implementation Details:
* **Frontend Code**: All network requests throughout the React application use standard relative URLs:
  ```ts
  const API_BASE = '/api';
  await fetch(`${API_BASE}/complaints`, ...);
  ```
* **Production Nginx (`frontend/nginx.conf`)**:
  ```nginx
  location /api/ {
      proxy_pass http://backend:8000/api/;
      proxy_http_version 1.1;
      proxy_set_header Host $host;
      proxy_set_header X-Real-IP $remote_addr;
      proxy_set_header X-Forwarded-For $proxy_add_x_forwarded_for;
      proxy_set_header X-Forwarded-Proto $scheme;
      proxy_pass_header X-Cache;
      proxy_read_timeout 30s;
  }
  ```
* **Development Vite Proxy (`frontend/vite.config.ts`)**:
  ```ts
  server: {
    proxy: {
      '/api': {
        target: 'http://localhost:8000',
        changeOrigin: true,
      },
    },
  }
  ```

---

## 5. Consequences

### Positive
* **Zero Environmental Rebuilds**: The multi-stage frontend Docker image is built once in GitHub Actions, scanned by Trivy, and deployed across any cluster or environment without modification.
* **No CORS Issues**: The browser sees all traffic as same-origin (`origin: /`), avoiding preflight roundtrips and CORS header mismatches.
* **Telemetry Passthrough**: Custom caching and triage headers (such as `X-Cache: HIT` and `X-Cache: MISS`) pass directly to the client application without stripping.
* **Security**: No internal service network names or IP addresses are exposed to the public internet.

### Negative / Trade-offs
* Nginx must be configured properly in all environments to resolve the backend service name.
* In Kubernetes, an ingress or edge gateway must route `/api` to the backend service if Nginx is bypassed at the edge (in our architecture, Nginx or Kubernetes Ingress manages this uniformly).
