# AUT-2202 · PostgreSQL launch tuning: prepared, not deployed

22 October 2026. Root run `9e04da68-09f4-469f-b7bd-283e95e9fec0`; audit linkage [AUT-63](/AUT/issues/AUT-63). Source baseline `98ecc8566e96ae33a23095be66fef41d485ce95d`. All changes are in the shared dev/live workbench, restricted to the claimed postgres command and new observation/test/evidence files. Foreign changes remain untouched.

## Requested source and actual verification

The postgres service now requests `shared_preload_libraries=pg_stat_statements`, `shared_buffers=512MB`, `random_page_cost=1.1`, and `jit=off`. Its pinned image, 2GiB/2CPU limits, 256MiB dynamic shared-memory mount, authentication and networks are unchanged. 512MiB is 25% of the database container limit, not 25% of host memory. PostgreSQL's main shared buffers use mmap; the existing /dev/shm size did not prevent this actual startup proof.

- Actual release-pinned image `postgres@sha256:1c59e2c3c818eaa0f0628f695b36e7c9e362d6b219b36a54a32df645cbd7e1af`, PostgreSQL 18.6, extension 1.12.
- Isolated fictional container: no network or host mounts, 0.5CPU/768MiB limit; actual source command. **2 passed in 6.01s, exit 0.** Proves startup values, observation before/after extension creation, bounded timing output without representative SQL/private marker, accidental-write rejection, and actual SQLSTATE 42501 for extension creation by a non-superuser even with database CREATE granted. Fixture containers removed; no live DB schema changed.
- Existing release security/network/profile/backup/rollback contracts: **5 passed, 97 deselected in 0.41s, exit 0**. These do not prove the restart failure path described below.
- Ruff check/format, `uv run python -c "import ac_platform.http"`, and owned-path whitespace checks passed. The first root pytest invocation used a relative path and executed no tests; the corrected absolute-path invocation and final enhanced run passed.

Run the fictional proof through the audited Root wrapper, using the absolute test path and `AC_POSTGRES_LAUNCH_DOCKER_TEST=1`. The default non-root test suite deliberately skips this operator-only fixture.

The repeatable diagnostic is `scripts/ops/postgres-launch-observe.sql`: `psql -XqAt -v ON_ERROR_STOP=1 -f -`, SQL supplied on stdin, credentials expanded only inside the selected existing container. It uses a read-only transaction, 5-second statement and 1-second lock timeouts, allowlisted settings and four table aggregates, at most 100 index definitions and 20 statement records. It never resets statistics, prints query text, or reads customer payloads. Missing public extension/preload is an explicit unavailable result. Query timing output is ranked by total execution time; planning collection remains off.

## Live baseline: settings remain unchanged

Both environments run core/web `df994ccc04e3e2449dcf5ae63be127df15fe8d92`. Staging is paused; production is manual. Release engine `bc49a3dddaab`. No `production.HELD-*` markers existed at the observation; their exact state must be preserved at any later action. No live service restart, settings/role/schema/data mutation, release, board impersonation or production hold change was made.

At 21:13:33Z staging and 21:13:46Z production both reported 128MiB shared_buffers, random_page_cost=4, jit=on, no preload and no extension; work_mem=4MiB, max_connections=100, compute_query_id=auto. Both had 13 connections. Staging database size 1,017,116,351 bytes; production 84,219,583 bytes. DB stats_reset is NULL, so these accumulated totals are not rates and their reset origin is unknown. Postmasters started 17:13:11Z and 17:20:28Z respectively.

| Environment/table | Accumulated seq scans | Accumulated seq rows read | Scans added in sample | Rows added in sample |
|---|---:|---:|---:|---:|
| Production runs | 2,457,266 | 2,724,388,493 | 185 | 242,720 |
| Production drafts | 647,034 | 346,648,582 | 0 | 0 |
| Production Brain4 | 549,618 | 31,672,539 | 0 | 0 |
| Production plans | 163,328 | 43,476,948 | 3 | 927 |
| Staging runs | 1,667,778 | 6,711,086,051 | 2 | 8,140 |
| Staging drafts | 8,995 | 31,118,702 | 0 | 0 |
| Staging Brain4 | 508 | 0 | 0 | 0 |
| Staging plans | 88,857 | 20,295,621 | 2 | 486 |

Cgroup CPU deltas: production **0.04929 cores over 11.39475s**, staging **0.06152 cores over 11.58347s**. This is a short baseline under current traffic, not a capacity benchmark or evidence of improvement. No after-deploy measurements exist. Use the same collector and interval after staging and production, retain counter reset/start information, and compare scan rates and CPU under comparable load. Do not subtract counters across a reset.

Host check: 15,992MiB RAM, 8,506MiB available; swap 4,090/4,095MiB occupied. Short vmstat si/so=0; memory PSI avg10=0.09%, avg60=0.20%. Cgroup memory.current staging=908,779,520 bytes and production=136,396,800 bytes; memory.high/max/OOM events all zero. The two buffers would add at most 768MiB compared with the old setting. There is measured headroom now, but full swap requires another pressure/cgroup check immediately before each restart. Do not clear swap or change host settings as part of this task.

## Required output before release

**Unblock owner: existing Orchestrator 2 / Align 3, with the Platform Engineer for the governed extension/restart implementation and required CTO review.** Return the selected immutable release source and controlled migration route; migration numbers are allocated by Align 3. Root remains the named staging/production executor through `ac-release` after those outputs exist.

1. `pg_stat_statements` preload only starts collection. Access requires extension SQL objects in the target database. This extension is not trusted and current `ac_migrator` is intentionally NOSUPERUSER/NOCREATEDB/NOCREATEROLE. The real pinned-image test proves that a normal Alembic CREATE EXTENSION fails with 42501. Supply a versioned privileged-extension migration executed through the release path with exact allowlisted authority; do not make ac_migrator superuser, grant broad privileges, or manually create the live extension.
2. The existing installer recreates Postgres **before** its pre-migration dump. Its failure handler also attempts to fence writers against the new server **before** restoring the old compose. If the new PostgreSQL fails to start, fencing can fail before the rollback reaches the old compose. Supply a tested startup-failure recovery path and verified pre-restart snapshot, preserving forward-only recovery after application write exposure. The current five passing contract tests do not resolve this source-level risk.
3. Include the finite config plus that extension/recovery output in the existing governed release. No competing ship, raw git integration, push, release hold removal or manual immutable edits. `ac-release` only installs already admitted main CI artifacts, so a workbench commit alone cannot be deployed here.
4. Root takes staging first in a quiet locked window, records image/source/backup digests, settings/extension/health read-backs, restart duration and recovery result. Announce the selected production interruption to the orchestrator; use the same admitted build. Preserve all production HELD markers. Collect post-change CPU/scan counters and top query timings without resetting existing history.

## Proposed API task (pending measured query timings, no indexes created)

Title: **API: index measured polling and latest-report lookups without changing query or billing authority.** Migration number from Align 3; do not invent one here. Input is the post-activation top-total-execution-time query IDs, calls, relation labels, durations and EXPLAIN plans against fictional representative data at 10–50x scale. Reconstruct statements from the pinned repository; do not put customer values or arbitrary SQL text in task evidence.

Source-derived candidates, not a measured missing-index verdict:

- `report_store.py:298`: runs filtered by recording_id, tenant_id, person_id and ordered created_at DESC, id DESC. Live indexes have no recording_id prefix. Assess `(recording_id, tenant_id, person_id, created_at DESC, id DESC)` against the actual timed query.
- `report_store.py:359` and `:513`: drafts filtered by recording/tenant/person and erased_at IS NULL, ordered created_at DESC, id DESC; sometimes also run_id. Assess a partial latest-draft index with the measured equality prefix. Existing `(run_id, report_sha256)` already covers some run_id lookups.
- `released_run_recovery.py:48`: nonterminal runs joined by job_id and ordered created_at/id. Assess a partial nonterminal index including the measured join/order prefix; do not change canonical minute or job state.
- `processing_plan.py:1708`: active/quoted, not erased, `(expires_at <= now OR active AND next_check_at <= now)` ordered next_check_at. Existing state and next_check_at indexes are present. Decide from the actual plan whether a partial composite/expiry index helps; do not assume the OR is solved by a simple state index.
- Brain4 already has `(recording_id, run_id, created_at)` and `(state, created_at)`. `brain4_shadow.py:363` additionally filters source/revision/saved/not-erased. A small table can reasonably choose a sequential scan. No duplicate Brain4 index is justified by scan count alone.

Acceptance: measured query-to-index mapping, real EXPLAIN evidence on fictional 10–50x data, migration upgrade/downgrade safety, unchanged authorization and ledger behavior, and before/after CPU/scan-rate evidence after the authorized release. This proposal remains provisional until pg_stat_statements is available.

## Retained evidence and source pins

Retained aggregate JSONL, baseline-summary.json and final test logs: `/home/acdev/strikes/2202/evidence/`. Baseline summary SHA256 `9a5402cbe33b16e755b5950c7348244b3a186c7d72e8eff7032c73c27b9c30ac`. Raw observations contain only the bounded diagnostic output and CPU counters; the run-owned scratch is disposable.

Task source documents: launch-readiness-plan revision `0383ac9f-2c6a-420e-ae40-8b15b988b359`, body SHA256 `aa0ba521e62a2731271e84890d8d994f83128e014369a9274ca86a0c0474c7c4`; launch-capacity-audit revision `69986afc-76eb-4f79-8d8e-b3b7cc1fcb7f`, body SHA256 `7d5b2883f55fbadbf7d912ae526d1bfe6b095243ca65b66ae6c677cfaf15197b`.

PostgreSQL primary references: [pg_stat_statements preload, restart and per-database extension](https://www.postgresql.org/docs/18/pgstatstatements.html); [shared_buffers and main shared memory](https://www.postgresql.org/docs/18/runtime-config-resource.html). These explain the configuration; actual pinned-image proofs above establish this host's executable result.

Exact prepared source SHA256:
- `infra/application/compose.yaml`: `e2bb58c57414eb194e4fa305bdc0ee07a5aa377957706b5990795ad67bcdca0e`
- `scripts/ops/postgres-launch-observe.sql`: `4032ec704e4c23b7c64470242c647474a074a2ab83ae54b9a10864d5e1ec76ef`
- `tests/infra/test_postgres_launch_tuning.py`: `eff8189621358539627d0324b2236a1bac8d6f1d1dc26ed5b0e1ef3c0f11a464`
