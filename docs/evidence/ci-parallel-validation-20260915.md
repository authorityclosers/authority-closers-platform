# Parallel application validation evidence

This checkout adds a parallel validation layout for the application workflow.
The existing validation run is left untouched while this layout is reviewed and
measured in a later CI run.

The workflow keeps the Academy capacity check, frontend formatting/lint/type
checks/tests/build, Python formatting/lint/type checks, the native AudioAtlas
and codec prerequisites, the scanner filesystem proof, migration and backup
proofs, privilege checks, PostgreSQL integration gates, registration browser
proof, and release packaging dependency on the aggregate `validate` job.

Python pytest files are discovered at runtime by
`scripts/ci/python_test_shard.py`. Four matrix jobs each receive an isolated
pair of PostgreSQL services. Database and integration paths receive higher
stable weights than infrastructure, browser, unit, and other paths; a
deterministic greedy assignment balances the resulting totals. The explicit
environment-specific gate files are recorded in
`scripts/ci/python-test-exclusions.txt` and run once by the gate job.

The aggregate job downloads all four manifests and fails if a shard is absent,
cancelled, skipped, duplicated, or if a newly added pytest file is missing from
the union. Component results are checked separately, so a successful manifest
check cannot mask a failed test job. Matrix `fail-fast` is disabled and
`max-parallel` is four to keep all shards independent without unbounded runner
concurrency. Each shard records JUnit skip messages and fails closed when a
codec, native runtime, or browser dependency is unexpectedly unavailable.

Local checks completed for this change:

- `uv run pytest tests/unit/ci/test_python_test_shard.py -q` — 3 passed.
- `uv run ruff check scripts/ci/python_test_shard.py tests/unit/ci/test_python_test_shard.py` — passed.
- `pnpm exec prettier --check .github/workflows/application.yml` — passed after formatting.
- PyYAML parse of `.github/workflows/application.yml` — passed.
- The current checkout discovers 350 pytest files, excludes 14 explicitly gated files, and assigns the remaining 336 files as 81/85/86/84 files with equal weighted totals of 630 per shard.

The wall time and runner cost of the parallel layout are intentionally not
claimed until a complete CI run records them.
