# AUT-428 call metrics store evidence

Updated: 2026-10-03
Source: `a286d72587d5583cae02440610ee35626d3b3379` (latest main at task start)
Branch: `task/platform/428-call-metrics-store`
Status: partial implementation; blocked on the shared files in AUT-311 / PR #244.

## Implemented independently

- Added the `conversation_call_metrics` model and ADR 0047. The model uses JSONB
  on PostgreSQL and JSON on SQLite, with SQL NULL for cleared summary content.
- Added the first-settlement writer in `ReportingPipeline.finish()`. Its
  savepoint isolates computation and insert errors from report completion.
- The writer hashes deterministic `call-metrics/2` summaries, copies only the
  validated outcome kind, and keeps the first report's measurements on reruns.
- Exceptions log `call_metrics_skipped` and the exception class only.

## Verified locally (fictional data only)

`uv run pytest -xq --tb=short tests/unit/conversation_intelligence/test_call_metrics_store.py tests/unit/conversation_intelligence/test_call_metrics.py`

Exit 0: **41 passed in 37.21 seconds**. The new store suite covers:

- SQLite table creation, duplicate primary-key rejection and SQL NULL clearing;
- PostgreSQL first-report persistence and preservation on a later report;
- a computation exception and a real PostgreSQL foreign-key insert failure,
  both preserving a completed settlement and durable report;
- exact content-free exception logging and no late retry after a first skip;
- outer transaction rollback removing the report, settlement and metrics together;
- an absent outcome remaining NULL.

The PostgreSQL tests migrate a disposable schema to current main, then explicitly
create the new metrics table from the model. Upstream provider receipt and actor
admission are stubbed. This proves the writer's persistence boundary, not the
pending migration or a full provider/API journey.

Repository Python checks, all exit 0:

- `uv run ruff format --check packages/python tests`: 909 files formatted.
- `uv run ruff check packages/python tests`: all checks passed.
- `uv run mypy packages/python`: no issues in 383 source files.
- `git diff --check`: clean.

The first fixture run failed because its synthetic checkpoints omitted required
parents. Corrected the checkpoint graph and reran the full focused suite above.

## Required continuation before a pull request

PR #244 adds migration 0070 and changes the same model-registry, erasure,
backup/restore and release-head catalogue files required by this card. The
delivery constitution prohibits overlapping PR files and simultaneous shared
migration changes. No overlapping file has been changed here.

After AUT-311 merges, continue this branch through `ac-gate check`, update from
main, and select the next unused migration ID (0055 was the original card ID;
0070 is now reserved by PR #244). Then complete:

1. Forward-only migration, canonical registry and all parity/release catalogues.
2. `finish_erasure` clearing summary and outcome, preserving content-free
   provenance for explicit deletion and expiry alike.
3. Fictional seven-day and 730-day inherited-retention cases in the allowed store
   suite. These fixtures issue no policy, consent revision or intake switch.
4. Migration/registry/parity checks, CI and CTO review with CEO approval for the
   sensitive migration change. Never self-merge.
5. After merge and dev deployment, a fictional dev API journey. No staging or
   customer-record check is authorized by the retention-v2 alignment.

No migration, deployed erasure or dev journey is claimed complete in this evidence.
