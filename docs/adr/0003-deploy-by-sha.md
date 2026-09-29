# ADR 0003: Immutable Container Deployment by Digest SHA

* **Status**: Accepted
* **Date**: 2026-09-26
* **Authors**: Jibran, Alishba
* **Context**: CivicPulse Assignment CS4032 (§3.2, §3.5)

---

## 1. Context and Problem Statement

In standard container deployment pipelines, using mutable tags such as `:latest` or dynamic semver branches (e.g., `:v1.0`) introduces non-determinism into production clusters:
1. Two nodes pulling `civicpulse-backend:latest` at different times may pull distinct image builds if a new image was pushed concurrently.
2. In Kubernetes rollouts, if an image tag does not change, Kubernetes `imagePullPolicy: IfNotPresent` skips pulling updated code, leading to stale pods.
3. Vulnerability scanning (Trivy) and provenance tracking cannot reliably certify a build if the image referenced can be overwritten in the registry (GHCR).

We need an immutable deployment mechanism that guarantees byte-for-byte reproducibility across local testing, CI vulnerability scans, and production Kubernetes deployments.

---

## 2. Decision Drivers

1. **Immutability & Determinism**: Every container deployed to Kubernetes must be mathematically guaranteed to match the exact build tested and scanned by CI.
2. **Reproducible Rollbacks**: Rolling back a deployment must restore the exact previous binary without re-building or risking tag mutations.
3. **Traceability**: Given a running pod in Kubernetes, an engineer or auditor must be able to trace it directly back to the exact Git commit SHA that built it.
4. **Supply Chain Security**: Enable static vulnerability scanners (Trivy) to pin scan results to cryptographic content addresses.

---

## 3. Decision Outcome

We enforce **Deploy-by-Digest (SHA-256)** across all CI/CD pipelines, Kustomize manifests, and Kubernetes deployments.

### Implementation Details:

1. **Build & Tag by Git SHA in CI (`.github/workflows/ci.yml`)**:
   During image compilation, images are tagged with both the git commit SHA (`${{ github.sha }}`) and their immutable content digest:
   ```yaml
   tags: |
     ghcr.io/${{ github.repository }}/backend:${{ github.sha }}
   ```

2. **Kustomize Set Image (`.github/workflows/cd.yml`)**:
   During CD deployment, `kustomize edit set image` updates the Kubernetes manifest with the specific immutable image SHA rather than a floating tag:
   ```bash
   cd k8s/overlays/prod
   kustomize edit set image backend=ghcr.io/${{ github.repository }}/backend@${DIGEST}
   ```

3. **Base Image Freezing in Dockerfiles**:
   The Dockerfiles themselves adhere to this decision by pinning official base images by their cryptographic SHA-256 digest:
   ```dockerfile
   FROM python:3.12-slim@sha256:f77ac9e44ae96ef2c90b8053ea08c31f8be030f824196b0ae4db6d462c84e51f AS builder
   ```

4. **Production Compose Manifest (`compose.prod.yaml`)**:
   In production Compose topologies, container images pin explicit versioned and digested references instead of relying on local image rebuilds.

---

## 4. Consequences

### Positive
* **Zero Drift**: Eliminates the "works on my machine / fails in cluster" discrepancy caused by floating tags.
* **Instant & Reliable Rollback**: Rollbacks (`kubectl rollout undo`) revert immediately to the previous immutable image digest already cached on the node, taking seconds rather than minutes.
* **Security Auditability**: Security scans (Trivy) in CI guarantee that what was scanned is exactly what is running in the pod.

### Negative / Trade-offs
* Image names in Kubernetes manifests are long cryptographic hashes (e.g. `@sha256:4b12...`), requiring automation tools (`kustomize edit`) rather than manual edits.
* Registry garbage collection policies must be configured with retention rules to prevent deleting active digests.


