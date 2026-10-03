# AUT-311 S4b1: dormant C5 speaker-role transport

Source pin: main `0f015cf3be91605223704289e35f7b6f22ff8eeb` (PR #253 merged).
Contract: ADR 0042 and AUT-311 plan rev 3, D7/D9. This bounded slice carries the
S4a names-free snapshot through StageRequest, preparation, durable intent replay
and worker result validation. Resolving/freezing the processing-plan column and
speaker-map report_basis remain the next S4 slice; model names remain S5.

- C4 and undeclared revisions refuse role-bearing requests. The declaring set
  remains empty. Legacy request serialization and v1–v6 prepared bytes are
  unchanged, including when the pure preparation helper is given roles.
- C5 validates against its projected C2 before preparing or saving task intent.
  A stale, malformed, unknown-speaker or name-bearing snapshot falls back to no
  roles with only `speaker_roles_snapshot_invalid` logged. The sanitized request
  is used for replay; invalid private fields never enter the durable intent.
- The worker gives the same snapshot and known prompt revision to the result
  validator. Missing/changed snapshots and a role block under an undeclared
  revision fail binding. This grants no prospect enforcement or identity claim.
- Fictional tests patch a declaring v3/v5 only in memory. Real calls, provider
  activation, scoring, profile changes and database changes are outside this slice.

Verification:

- **329 distinct unit/regression tests passed** across speaker-role dispatch,
  report input, source context, inference tasks, prompt revisions, broker routing,
  retained C5 recovery, reports, processing plans, Gemini tasks and v5/v6 integration.
- `uv run pytest tests/database/test_conversation_reporting_pipeline_postgresql.py -q`:
  **4 passed**, using the configured disposable loopback database and fake broker.
- `uv run ruff format --check packages/python tests`,
  `uv run ruff check packages/python tests`, `uv run mypy packages/python`: passed.
- `reports.py`, `processing_plan.py` and `speaker_map_service.py` exactly match
  pinned main; legacy prompts and validator source identity are unchanged.

Dev check: <https://salesxray-dev.authorityclosers.com>. Run
`uv run pytest tests/unit/conversation_intelligence/test_speaker_roles_dispatch.py -q`
(13 cases). The pipeline boundary stubs checkpoint reads/save and alignment,
but uses actual checkpoint hashes, preparation, intent replay and result binding.
The existing PostgreSQL suite covers normal durable dispatch. This dormant slice
adds no visible call behavior. Dev web returns 302, readiness/OpenAPI return 200;
running OpenAPI still omits speaker-map, so live S3 behavior remains unverified.
