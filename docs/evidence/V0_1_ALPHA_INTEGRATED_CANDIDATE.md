# v0.1-alpha integrated candidate evidence

Status: integrated candidate; bounded exact staging deployment/controller
smoke is recorded, and production approval is not claimed.

## Candidate lineage

- Reviewed base: `446b1b9f71735170a06bec074e114fb8294ef230`.
- UI component promotion: `f29599642e1bb95b4e260a092567de39c8ad92d2`.
- Media vertical slice: `5e9adc50bb8752e80113f283d84ade61e3f41e19`.
- Local authenticated QA bridge: `830ab7313e3010ba9d8a1e7913ea42b4d97d50f6`.
- Planning and analytics: `8c6248ce3d007bd57704b6ce39dccd1eb7b8ad00`.

The immutable release `5c7333c5a588f5209acd5ca9b5ce0e03e20e16a4` is the
staging artifact covered by
[EVD-005 exact staging controller smoke](../knowledge/v0.1-alpha/EVD-005-exact-staging-5c7333c5.md).

## Historical migration normalization

The integration verification recorded for the earlier candidate stopped at a
linear head of:

`20260901_0012 -> 20260902_0013_media_contracts -> 20260902_0014_planning_analytics`

That candidate renamed the planning migration and updated its `down_revision`;
migration operations and durable table semantics were unchanged. The exact
staging release named above subsequently adds
`20260903_0015 -> 20260903_0016`, and its deployed migration head is
`20260903_0016` as recorded in EVD-005.

## Verification

- `uv run pytest -q`: **909 passed, 122 skipped, 1 warning**. Skips are
  environment-gated PostgreSQL, Docker, POSIX, or Playwright checks.
- Focused integration suite: **66 passed**, 1 Starlette/httpx deprecation
  warning.
- `uv run mypy packages/python`: passed; 112 source files.
- Root format check, lint, and typecheck: passed.
- Learner web tests: **265 passed**; typecheck and lint passed.
- Historical candidate check: `uv run alembic heads` returned one head,
  `20260902_0014`. Exact-release deployment proof records the later single head
  `20260903_0016`.
- `uv run alembic check`: not executable without the required
  `AC_DATABASE_MIGRATOR_URL`; no database URL was invented or committed.
- Next Webpack build compiled successfully and completed TypeScript, but local
  page-data collection hit Windows dependency filesystem I/O (`UNKNOWN` open
  error). No source compile error remained.
- POSIX infrastructure shell proof is host-blocked because the available WSL
  instance cannot mount its local disk; the Python infra archive race passed on
  isolated rerun.

## Capability gates still open

- Media providers, storage, scanning, processing, and recording remain
  fail-closed and require their governance approvals.
- Analytics consent, retention, controlled promotion, and Calendar exposure
  remain capability-specific gates; analytics cannot become canonical progress,
  access, payment, completion, or score state.
- Authenticated browser proof must use the approved staging origin or complete
  review of the development-only bridge; localhost must not forward staging
  cookies or forge Origin.
- Exact-SHA CI/package and bounded staging controller smoke are recorded for
  the named release. Full browser/device, capability, backup/restore,
  rollback, security, observability, and action-time gates remain required.
  Production is NO-GO.
