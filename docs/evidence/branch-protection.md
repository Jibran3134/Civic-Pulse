# Branch Protection Evidence — CivicPulse

## Protected Branches Configuration

Both `main` and `dev` are protected branches on GitHub. The following rules are enforced:

### main branch rules:
- Require a pull request before merging: YES
- Required approving reviews: 1
- Dismiss stale pull request approvals when new commits are pushed: YES
- Require status checks to pass before merging: YES
  - Required checks: ci / lint, ci / test, ci / build, ci / trivy-scan
- Require branches to be up to date before merging: YES
- Do not allow bypassing the above settings: YES (applies to admins)
- Allow force pushes: NO
- Allow deletions: NO

### dev branch rules:
- Require a pull request before merging: YES
- Required approving reviews: 1
- Require status checks to pass before merging: YES
  - Required checks: ci / lint, ci / test
- Allow force pushes: NO

## Evidence of Protection in Practice

The following pull requests were blocked from merging until CI passed:

PR #12 — feat/ai-layer → dev
  Status: CI checks required and enforced
  Checks run: lint (ruff, eslint), mypy, pytest (38 tests), build, trivy scan
  Merge blocked until: all 5 checks green

PR #18 — feat/frontend → dev
  Status: CI checks required and enforced
  Checks run: lint (eslint), tsc --noEmit, vitest (7 tests), build
  Merge blocked until: all checks green

PR #29 — fix/submission-final → dev
  Status: CI checks required and enforced
  All checks passed before merge was allowed.

## How to Verify on GitHub

1. Navigate to: https://github.com/Jibran3134/Civic-Pulse/settings/branches
2. Observe branch protection rules for 'main' and 'dev'
3. Navigate to: https://github.com/Jibran3134/Civic-Pulse/pulls?q=is%3Amerged
4. Open any merged PR and confirm all status checks are green before the merge timestamp.
