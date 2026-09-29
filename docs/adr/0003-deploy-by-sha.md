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
