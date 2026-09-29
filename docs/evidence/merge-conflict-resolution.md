# Merge Conflict Resolution — `backend/app/core/config.py`

**Branch merged**: `feat/atomic-rate-limiter` into `feat/ollama-retry`  
**Conflict file**: `backend/app/core/config.py` lines 72–126  
**Date**: 2026-09-27

---

## Saved conflict markers (before resolution)

See [`merge-conflict-markers.txt`](merge-conflict-markers.txt) for the exact
output of `Select-String` on the conflicted file before any edits were made.

The conflict arose because both branches inserted new `Field` declarations
immediately after `stats_cache_ttl_seconds` — the conventional "end of the
field block" — at the same line in the class body.  Git could not determine
which insertion was authoritative, so it flagged the entire region.

## Resolution decision

**Both blocks were kept in full, in the order: triage settings first, then
rate-limiter switches.**

Neither set of settings supersedes the other: the triage settings
(`OLLAMA_BASE_URL`, `OLLAMA_MODEL`, `TRIAGE_TIMEOUT`, `TRIAGE_MAX_RETRIES`,
`TRIAGE_RETRY_BASE_DELAY`, `TRIAGE_CACHE_TTL_HOURS`) govern how the AI
provider layer behaves, while the rate-limiter settings
(`RATE_LIMIT_ENABLED`, `RATE_LIMIT_FAIL_CLOSED`) and their `_positive`
validator govern how the Redis token-bucket limiter behaves — completely
independent subsystems.

Triage settings were placed first because they belong with the existing
`triage_provider` field directly above; rate-limiter switches follow
immediately after, preserving the grouping Jibran established in his branch.
The `_check_triage_provider` `@field_validator` (from `feat/atomic-rate-limiter`)
and the `_positive` `@field_validator` (also from `feat/atomic-rate-limiter`)
were both preserved without modification; discarding either would have
silently removed start-up validation that both of us rely on.

## What was NOT kept from each side

Nothing was dropped from either side.  The only change from the raw conflict
state is the removal of the three git marker lines (`<<<<<<<`, `=======`,
`>>>>>>>`).
