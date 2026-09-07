# Explicit platform / Academy Studio capability persistence

Status: local implementation checkpoint, **not activated or deployed**.
Worktree: existing `d2de`, branch `codex/local-staging-dev-bridge`.
Base: `99867fe4e6a1d7d8188f85e3b3808bf59723fc2c`.

## Implemented

- Immutable capability grants and separate immutable revocations, forward-only
  migration `20260907_0019`, exact tenant/program FK and scope/action checks.
- Platform capabilities have their own namespace; Studio permissions are
  individually tenant/program scoped. No wildcard, email allowlist, speculative
  Instructor role, role replacement or enrollment bypass.
- Transactional named-session grant/revoke service, UUID intent replay,
  conflicting-intent denial, current verified person/lifecycle checks and
  original replay that cannot reactivate a revoked assignment.
- Same-transaction audit using real resource tenant or configured platform
  governance audit context. A suspended subject's grant remains revocable.
- Narrow operator-only first-manager bootstrap for the exact existing verified
  operations owner, only before capability history exists. No automatic login
  invocation, identity creation, membership change or public bootstrap route.
- All new models registered for migration drift checks; current-head regression
  expectation advances to 0019. No historical migrations were modified.

## Verification and review

Root focused tests: **74 passed in 6.40 seconds** across service/scope/audit,
database constraints and model registry. The service tests execute actual
relational SQLite queries and canonical audit code through an awaitable adapter;
they do not pretend SQLite proves PostgreSQL locking.

Full package Ruff and formatting checks passed; mypy passed 143 source files.
The existing restore tests pass after preserving their shared contract:
**57 passed, 13 environment-dependent skips** in 6.26 seconds (including ten new
PostgreSQL capability tests, Docker/approved-dump/POSIX-specific checks).

The schema agent reviewed the independently root-authored application service;
root reviewed its schema, constraints, migration and tests. Three findings were
addressed: lifecycle reads now hold shared resource locks, a namespaced
advisory governance fence avoids the ordinary-identity/tenant exclusive-lock
cycle, and bootstrap replay resolves the exact command with original audit
provenance instead of choosing an unordered row. Separate fresh-review spawn
was unavailable because the agent thread limit was reached; a final integrated
review remains a release gate, not a claimed completion.

Ten disposable PostgreSQL tests are written for populated 0018→0019 migration,
metadata parity, SQL immutability, cross-tenant FK, real canonical service
grant/replay/revoke/rollback/audit, normal identity/management lock interaction
and observed blocked lifecycle writes. **Not run locally:** no disposable local
PostgreSQL is configured. They must run in Linux CI before merge/activation.

## Broader-regression observation

The initial full unit/database run was intentionally interrupted after it
stopped producing output around the pre-existing cancellation timing tests.
The exact isolated intelligence test file passed 25 tests in 0.17 seconds. Inspection
found an unbounded test wait for provider startup even though its 10 ms request
deadline can expire before provider entry. The test now bounds that wait and
drains the generation task in cleanup; it does not change AI runtime behavior,
enable providers or loosen the timing assertion. Its 25 tests pass in 0.15 seconds.
The replacement full run used pytest's 30-second fault-handler diagnostics and
completed: **1,246 passed, 31 PostgreSQL-dependent skips, one pre-existing
Starlette/httpx deprecation warning in 46.69 seconds**. The interrupted run is
not a pass, and skipped PostgreSQL cases still require CI execution.

## Not yet done / next acceptance

No account grants, migration runs, CLI actions, learner writes or VPS changes
occurred for this checkpoint. Runtime auth and permissions are unchanged.
The existing four backend enforcement seams and two frontend entry checks
must be integrated together, with resource-filtered Studio collections and
normal named authentication. See ADR0031 for exact seams and lock ordering.

The 39-table backup parity contract is shared by two foundation helpers and
the application controller. An attempted application-only extension failed its
real compatibility test and was removed. Version-compatible explicit grant/
revocation restoration proof is required before populating the new permission
state. The earlier a5/0018 restore proof does not certify 0019 rows.

After those gates: persisted operator access, reviewed film-on release,
canonical technical-film publication and actual learner playback. The full
Alpha UI/feature/performance/PWA/production objective remains unchanged.

## PR43 first Linux/PostgreSQL run — fixture correction

Application run `34145542979` at exact head
`abbe6053e278f55d5d601c10b6fd94d1011bdcf1` failed: **4 failed, 1,674 passed,
28 skipped**. Migration, least-privilege roles, backup-role dump, catalog locking
and six capability PostgreSQL cases passed. Four real-service/concurrency cases
failed before their assertions: the shared fixture added membership and session
without flushing the referenced composite membership key first. PostgreSQL
correctly rejected the session FK. The fixture now flushes membership before
adding the selected-tenant session. No constraint, assertion, runtime code or
authorization rule was weakened. A fresh Linux run is required to verify all
four formerly blocked service/locking cases; this correction is not a pass claim.
