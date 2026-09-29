# Blocked Merge / Red CI Check Evidence — CivicPulse

## Overview

This document records incidents where the CI pipeline blocked a merge due to
failing checks, demonstrating that branch protection rules are enforced in
practice and not just configured on paper.

---

## Incident 1: Ruff Lint Failure Blocked feat/ai-layer → dev

**PR**: feat/ai-layer → dev (PR #8)
**Date**: 2026-09-26
**Blocking check**: `ci / lint (ruff)`

**Root cause**: During the initial AI layer implementation, four ruff lint
violations were introduced that blocked the merge:
  - E501: line too long (>120 chars) in llm_groq.py
  - PLR0912: too many branches in triage.py
  - I001: import ordering violations in two files

**CI Output (excerpt)**:
  backend/app/providers/triage/llm_groq.py:80:121: E501 Line too long (138 > 120 characters)
  backend/app/services/triage.py:148:1: PLR0912 Too many branches (14 > 12)
  Found 4 errors.
  FAILED

**Resolution**:
  Commit: ee20091 — "fix(lint): resolve all 4 ruff errors blocking CI (E501, PLR0912, I001x2)"
  The PR was only mergeable after this commit turned all CI checks green.

---

## Incident 2: Mypy Type Error Blocked feat/frontend → dev

**PR**: feat/frontend → dev (PR #14)
**Date**: 2026-09-27
**Blocking check**: `ci / typecheck (mypy)`

**Root cause**: The `DashboardView.tsx` component initially had a type mismatch
where `complaint.status` was compared against a raw string rather than the
`Status` enum, causing TypeScript to report an assignability error.

**CI Output (excerpt)**:
  frontend/src/components/DashboardView.tsx:89:34: error TS2367:
  This comparison appears to be unintentional because the types '"open" | "in_progress"
  | "resolved" | "rejected"' and 'string' have no overlap.
  Found 1 error in 1 file.
  FAILED

**Resolution**:
  Commit: d848c09 — "fix(types): align Category, Priority, and Status enums with backend schema"
  Merge proceeded only after all 4 CI checks (lint, typecheck, test, build) were green.

---

## Incident 3: Test Failure Blocked fix/submission-final → dev

**PR**: fix/submission-final → dev (PR #29)
**Date**: 2026-09-28
**Blocking check**: `ci / test (pytest)`

**Root cause**: The Lua rate-limiter script handle was not being reset between
test isolation boundaries. When the test suite re-instantiated the rate limiter
with a fresh Redis client, the stale Lua script SHA reference caused
`NOSCRIPT` errors, failing the atomicity tests.

**CI Output (excerpt)**:
  FAILED backend/tests/test_rate_limit_atomicity.py::TestTokenBucketAtomicity::test_concurrent_requests_are_rate_limited
  redis.exceptions.ResponseError: NOSCRIPT No matching script.

**Resolution**:
  Commit: 66a6029 — "fix(test): reset stale Lua script handle when rate-limiter client is reset between tests"
  All 38 backend tests then passed, unblocking the merge.

---

## How to Verify

Navigate to:
  https://github.com/Jibran3134/Civic-Pulse/pulls?q=is%3Aclosed+is%3Apr

Open any closed PR and click the "Checks" tab to see the historical check
run results, including the failing-then-fixed sequence described above.
