# Local Practice Arcade: persisted attempts and earned-only pilot

Status: backend implemented and independently reviewed; isolated PostgreSQL proof passed. After review, the parent release owner reported the managed **local** sandbox migration 0019→0020 and API restart succeeded, with readiness HTTP 200. Browser acceptance and deployed-environment activation are not claimed here.

## Approved boundary

The user approved 10 earned credits and 30 XP for the first two distinct eligible set families completed per local day, and 40 credits once per ISO week after three actual practice days. Completion requires all required responses and explicit acknowledgment of authored feedback; reference-match accuracy is not eligibility. Unlimited new practice remains possible without purchased credits, deductions, transfers, official course progress, assessment scoring, certificates, or payments.

Current editorial definitions remain behind the existing explicit **local/test only** preview flag. They are not represented as Dipak-approved assessment or competition content.

## Implemented

- Server-issued UUID attempts pin a full private content snapshot and digest; public rendering and deterministic response validation both use that pinned version. Different source versions retain the same family reward-dedup identity.
- Tenant/person/session admission is freshly rechecked before reads, writes and idempotent replays. The normal selected academy, active verified person, active session and active membership remain mandatory; caller permissions are not authority.
- Responses and acknowledgments are append-only. Learners can revise an unacknowledged answer or restart its branch, while acknowledgment must address the latest terminal feedback. Earlier answers remain history. Canonical item order and expected revisions prevent stale or out-of-order mutation.
- Completion, participation, reward claims, the balanced earned-credit/XP journal, request-idempotency record and existing hash-chained audit all share one transaction. There is no public completion/reward/clock selector.
- A per-person database lock serializes competing attempts and calendar commands. Separate unique constraints enforce family/day dedup and two daily slots. Weekly dedup is independent of request IDs and attempt IDs.
- Nine tables are registered and frozen in forward-only migration `20260908_0020`. Seven history tables reject UPDATE/DELETE through ORM and PostgreSQL triggers. Deferred PostgreSQL constraints require both sides of each claim's exact credit/XP amount to commit together.
- Practice timezone initially has no default: the learner must explicitly save a valid, exact IANA name. Changes are audited and take effect next ISO Monday in the existing zone. The effective instant is persisted; reads derive the scheduled zone without changing historical day/week buckets. A different request while a change is pending returns a recoverable conflict.
- `/v1/practice/profile`, `/progress`, `/sets/{set_id}/attempts`, `/attempts/{id}`, `/responses`, and `/feedback/{id}/acknowledge` expose resumable projections. Every mutation requires Origin and Idempotency-Key. Tenant/person/award/time selectors and extra body properties are rejected.
- Practice's authenticated transaction dependency has function scope: deferred commit must succeed **before** a success HTTP body can be emitted.

## Verification

- `tests/unit/test_practice_engine.py` plus existing `tests/unit/http/test_practice_routes.py`: **37 passed**, 10.93 seconds. Real SQLite relational/FK/audit execution, all eight set families/seven comparators, revised and branching responses, version pinning, stale replay rejection, required acknowledgment, 180-credit/420-XP weekly maximum, tenant/person/session isolation, calendar/DST boundaries, scheduled timezone changes, immutable ORM history and failure-injected full rollback.
- The ASGI commit-failure regression executes a real command then raises at dependency transaction exit. It verifies HTTP 500, no successful attempt/reward body, and rolled-back attempt/idempotency data.
- `tests/database/test_practice_engine_postgresql.py`: **20 passed**, 19.69 seconds against a fresh random schema on loopback PostgreSQL. Proof covers populated 0019→0020 upgrade with zero registry drift; fourteen direct-SQL UPDATE/DELETE history rejections; NULL daily-slot and missing balanced journal commit rejection; an observed `pg_blocking_pids` duplicate acknowledgment race; same-family dedup and three-distinct-family concurrent caps; actual awarded-journal savepoint rollback; and scheduled timezone/ISO-week rollover without rebucketing old receipts.
- PostgreSQL tests create and drop only their random `practice_engine_*` schemas. They do not migrate or seed the running `ac_local_sandbox` database.
- Ruff passed; nine scoped Python files format-clean; strict mypy passed for five source modules.
- Existing stateless Arcade and supplied-handoff regressions: `tests/unit/test_practice_arcade.py` and `tests/unit/test_arcade_handoff_assets.py`: **65 passed**, 0.33 seconds.

## Parent-owned local activation evidence

Before the running sandbox migration, the parent created a private custom-format local backup and read back its table of contents: 450,160 bytes, SHA-256 `c37adefc26e95fbb6ef5c0d44d67a9ef6ff4f3862a835a65dd6aee83283ffd45`. The parent then ran the normal managed migration/restart and reported readiness 200. This was local sandbox activation only; no production/VPS state or real learner database was changed.

## Review corrections

Parent independent review caught duplicate generated PostgreSQL unique-index names, restrictive answer revision behavior, and success responses potentially preceding dependency commit. Each was corrected and regression-tested. The NULL daily-slot SQL three-valued-logic hole was corrected with explicit non-null validation. The first PostgreSQL migration run exposed a PL/pgSQL CASE-expression grammar issue; fresh corrected migration and the full PostgreSQL suite passed. Exact IANA-name membership also prevents Windows case-insensitive filesystem resolution from silently accepting noncanonical `utc`.

## Follow-ups / not claimed

- Parent owns managed local backup, sandbox migration/restart and browser acceptance. No push, CI run, deployment or production activation occurred in this task.
- At initial activation, the progress projection performed up to roughly sixty detail queries for twenty recent attempts. The subsequent [bounded-query follow-up](20260908_PRACTICE_PROGRESS_BATCHING.md) removes that N+1 behavior; it does not claim a production latency target.
- Production content approval, practice-answer retention/deletion policy, recovery parity for schema 0020, provider or payments activation, public leaderboard policies and official scoring remain separate gates. Existing fail-closed recovery-head contracts have not been weakened.
- No fabricated streak, achievement, rank, cash balance or official learning progress is emitted.
