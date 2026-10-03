# AUT-428 call metrics store evidence

Updated: 2026-10-03
Source: `8b07d11` (main merged into the existing task branch for this continuation)
Branch: `task/platform/428-call-metrics-store`
Migration: `20261003_0071`; down revision `20261003_0070`
ADR: `docs/adr/0047-per-call-measurements.md`

## Implementation

- `conversation_call_metrics` stores one first-report numeric summary per usage
  settlement. JSONB on PostgreSQL has a SQLite JSON variant and clears to SQL NULL.
- `ReportingPipeline.finish()` writes deterministic `call-metrics/2` summaries
  inside a savepoint in the completed-settlement transaction. It copies only the
  validated outcome kind and keeps the first measurements on report reruns.
- Computation and real FK insert failures leave the report completed. Exceptions
  log `call_metrics_skipped` and the exception class only; no words or traceback.
- `finish_erasure()` clears summary and outcome for the recording and tenant,
  retaining IDs, rules, creation time and summary hash as content-free provenance.
  Expiry and explicit deletion both use that hook. Measurements inherit recording
  retention; they receive no separate retention deadline or reason exemption.
- Registered the model and the forward-only migration. Original card ID 0055 was
  superseded by the next unused ID 0071 after the merged speaker-map migration
  0070. ADR 0047 was still available.
- Backup, restore proof and restore drill all include the table in migration
  0071's `ac-postgres-parity-v43` catalogue; release-head fixtures now use 0071.

## Verification (fictional data only)

The PostgreSQL harness migrates a disposable loopback schema through 0071. It
creates no model-only table. Upstream provider receipt and actor admission remain
stubbed; these checks exercise persistence and erasure, not a full provider/API
journey. No real recording, provider or remote database is used.

Focused command:

```sh
uv run pytest -xq --tb=short \
  tests/unit/conversation_intelligence/test_call_metrics_store.py \
  tests/unit/conversation_intelligence/test_call_metrics.py \
  tests/database/test_model_registry.py \
  tests/database/test_conversation_postgresql.py::test_populated_migration_head_matches_real_model_registry \
  tests/infra/test_ac_release.py
```

Exit 0: **143 passed in 122.97 seconds**. Coverage includes:

- SQLite model creation, duplicate key rejection and SQL NULL content clearing;
- migrated PostgreSQL first-report persistence and rerun preservation;
- computation failure and real FK insert failure without report failure;
- content-free logging, no late retry after a first skip, absent outcome;
- outer rollback removing report, settlement and metrics together;
- seven-day legacy and 730-day future-policy recordings, each tested for expiry
  and explicit erasure. The real scheduler, deletion command, recovery fence,
  internal job lease and `finish_erasure` run. The fictional source has no objects
  to erase. Before adapter confirmation the row remains; afterwards summary and
  outcome are SQL NULL, the draft is cleared, and settlement/provenance survive;
- registry/migration schema drift and release-head recognition/refusal.

An initial fixture run used the internal job's zero recovery generation rather
than the worker's global generation. Corrected it to read the real recovery fence
at claim time. A misplaced logging assertion was also corrected before rerun.

Python format, lint and type checks pass (913 formatted files, 385 typed source
files). The new migration and three parity helpers also pass Ruff format/lint.
A standalone import check confirms all three 0071/v43 catalogues agree on 127
exact tables. `git diff --check` is clean.

Root-owned metadata parity tests are not claimed passed locally: local sudo is
unavailable and the unprivileged suite skips all 3381 cases. The repository's
root control-plane CI gate must run them before approval, along with the Python
test shards. CI results remain pending until the PR completes.

## CTO review correction (2026-10-03)

Reproduced the review's strict-zip failure in
`test_versioned_contracts_match_all_new_migration_tables_exactly`: migration 0071
was present in `HEADS`, but both expected tuples ended at 0070. Added the explicit
127-table count and `ac-postgres-parity-v43` contract for 0071.

Direct invocation of the three read-only catalogue tests passed:
checked-in revision identity, separately packaged helper agreement, and exact
migration-table/count/contract matching. This executes their assertions without
the module-wide root skip; no root-owned metadata validation is claimed.

```sh
uv run python - <<'PY'
from tests.infra import test_capability_backup_parity as parity

parity.test_compatibility_head_catalogue_contains_only_actual_checked_in_revisions()
parity.test_three_separately_packaged_helpers_have_identical_versioned_contracts()
parity.test_versioned_contracts_match_all_new_migration_tables_exactly()
PY
uv run pytest -xq --tb=short \
  tests/infra/test_ac_release.py tests/database/test_model_registry.py
uv run ruff format --check packages/python tests
uv run ruff check packages/python tests
uv run mypy packages/python
```

Exit 0: all three catalogue tests passed, **96 pytest tests passed in 9.79
seconds**, and format/lint/types passed. The root control-plane validation and
Python shards must pass on the corrected PR head before SHA approval.

## Review and deployment follow-through

This is sensitive (model, migration, erasure and backup parity): CTO review then
CEO approval, after the Python test shards pass. The watchdog merges; this task
is not done on approval.

After merge and dev deployment, run a fictional call's authenticated dev API
journey with the existing approved QA transport. Check exactly one metrics row
for its first completed report and `rules = call-metrics/2`, rerun preservation,
and explicit erasure through the app. Read counts/rules/null-state only; no
customer content. Record the deployed commit and dev result on the task, then
confirm staging visibility through the release train. No deployment or API
journey is claimed complete in this evidence.
