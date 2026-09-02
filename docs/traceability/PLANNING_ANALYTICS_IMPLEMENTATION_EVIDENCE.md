# Planning and analytics implementation evidence

This proposal is ported into the G1 foundation without the obsolete standalone
`apps/api`, `apps/web`, root `pyproject.toml`, or raw SQL migration directory.

Implementation seams:

- `packages/python/ac_platform/http/planning.py` — authenticated route contracts,
  source-separated projections, consent and retention gates.
- `packages/python/ac_platform/learning/planning_models.py` — tenant/person-
  scoped proposal read models and disposable analytics records.
- `packages/python/ac_platform/learning/planning_repository.py` — transaction-
  bound SQLAlchemy adapter with retention purge and idempotent event insert.
- `db/migrations/versions/20260902_0014_planning_analytics.py` — normalized
  Alembic chain migration after the integrated Media `20260902_0013` revision.
- `apps/learner-web/app/calendar/` and `calendar-runtime.tsx` — explicit-plan
  Calendar surface using the existing learner shell.

Verification:

- `uv run ruff check packages/python/ac_platform db/migrations/versions/20260902_0014_planning_analytics.py tests/unit/http/test_planning_routes.py tests/database/test_planning.py`
- `uv run pytest tests/unit/http/test_planning_routes.py tests/database/test_planning.py tests/unit/http/test_app_composition.py tests/unit/telemetry/test_telemetry.py -q` — 43 passed.
- `pnpm --filter @ac/learner-web typecheck` — passed.
- `pnpm --filter @ac/learner-web lint` — passed.
- `pnpm --filter @ac/learner-web test` — 248 passed.
- Production build run from `apps/learner-web` after the port; Node 22 emitted
  the repository's existing Node >=24 engine warning while compiling.

The implementation was not deployed. Promotion, retention, verified consent,
and any production analytics activation remain controlled gates.

Integrated candidate chain and current verification are recorded in
`docs/evidence/V0_1_ALPHA_INTEGRATED_CANDIDATE.md`.
