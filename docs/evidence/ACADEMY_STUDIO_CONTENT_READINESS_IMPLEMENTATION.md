# Academy Studio shell + content readiness implementation evidence

- Evidence date: 2026-09-04
- Release state: implementation candidate only
- Deployment state: not deployed by this slice
- Migration head resolved immediately before implementation: `20260903_0016`
- Candidate migration head: `20260904_0017`

## Implemented boundary

Academy Studio now exists inside the current `apps/admin-web` application. It
does not create an Instructor application, hostname, identity system, backend
or authorization role.

Browser routes:

- `/studio` — selected-tenant draft backlog and exact publication readiness;
- `/studio/programs` — selected-tenant programs plus immutable global
  read-only content;
- `/studio/programs/{programId}` — visible version provenance, topology,
  readiness blockers and authorized tenant-local publication;
- `/catalog` — redirects to `/studio/programs`.

API routes:

- `GET /v1/admin/studio/readiness`;
- `GET /v1/admin/studio/programs`;
- `GET /v1/admin/studio/programs/{program_id}`;
- hardened `POST /v1/admin/program-versions/{program_version_id}/publish`.

The reads require `catalog_read`, which is assigned only to the existing
`owner` and `admin` roles. They derive tenant scope from the verified product
session and revalidate active person, tenant and membership state. A selected
tenant can see every working draft; only older immutable history is bounded
and explicitly marked as truncated. Global programs are visible only when an
immutable version exists, and only bounded published/superseded global
versions are returned. Another tenant's resources and global drafts are not
disclosed. The database regression suite exercises 56 tenant drafts and
confirms none are hidden by the immutable-history limit.

## Truthfulness and actionability

The Today surface lists the real selected-tenant draft backlog oldest first
and reports oldest-work age from the canonical creation timestamp and response
time.
Readiness calls the same catalog structure, provenance, digest and
supersession checks as publication; it adds no speculative completeness rule.
Arrival rate, service rate and planned capacity are returned as structured
`unavailable` values with an explanation because this slice has no canonical
operational work-item timestamps or capacity plan. Simulation output is not
presented as live telemetry.

`AdminShell` filters Studio and support navigation using the verified named
permissions. This is discovery behavior only; every API retains server-side
authorization.

## Publication integrity

Publication now requires all of the following before the domain mutation:

- active selected-tenant owner/admin membership;
- `catalog_publish`;
- a bounded non-blank operator reason;
- an `Idempotency-Key` whose raw value is not persisted;
- the exact strong `If-Match` ETag returned for the reviewed draft.

The ETag covers version lifecycle/provenance plus the canonical module,
prerequisite and activity digest. The `catalog_publish_commands` ledger stores
only the key digest, request fingerprint and stored semantic response. Ledger
reservation, row-locked catalog publication, append-only audit event and
ledger completion share the authenticated caller-owned transaction. Exact
replay returns the stored result without another publication or audit event;
different intent under the same key is rejected; stale content fails without
publication. ORM and PostgreSQL trigger guards prohibit deletion and allow
only the single `pending` to `completed` transition.

## Validation run

The following checks passed in the persistent release worktree:

- `uv run alembic heads` — one head, `20260904_0017`;
- Ruff format/check on the changed Python, migration and focused test files;
- `uv run mypy packages/python/ac_platform/catalog packages/python/ac_platform/http/admin_learning.py packages/python/ac_platform/http/auth.py` — success;
- focused catalog/admin HTTP/database/composition tests — 80 passed;
- full Python unit suite plus `tests/database/test_catalog.py` — 896 passed;
- admin-web ESLint — passed with zero warnings;
- admin-web TypeScript check — passed;
- admin-web Vitest suite — 126 passed;
- admin-web production build — passed and emitted `/studio`,
  `/studio/programs`, `/studio/programs/[programId]`, and `/catalog`;
- `git diff --check` — passed after implementation and review resolution.

Independent read-only review and narrow re-review found no remaining
code-level Critical or Important issue. The reviewer still withheld promotion
pending the PostgreSQL integration gate described below.

The local frontend runner used Node 22.17.0 and therefore emitted the
repository's engine warning (`>=24 <25`). Lint, typecheck, tests and build all
passed, but the release pipeline must repeat them under the declared Node 24
runtime.

The PostgreSQL admin HTTP integration module collected successfully but its
four cases skipped because neither `AC_ADMIN_LEARNING_HTTP_POSTGRES_TEST_URL`
nor `AC_TEST_DATABASE_URL` is configured. Docker Desktop is not running on the
host, so a disposable local PostgreSQL service could not be started. The
checked-in cases cover the fresh migration, selected/global/other-tenant
visibility, unavailable metrics, exact publish replay, one audit event and one
completed ledger row. They also prove that an unknown publication target
returns unavailable without leaving a command or audit row. These tests and
exact-artifact browser proof remain mandatory before promotion.

## Files carrying the evidence

- Domain/persistence: `packages/python/ac_platform/catalog/models.py`,
  `packages/python/ac_platform/catalog/services.py`, migration
  `20260904_0017_catalog_publish_command_ledger.py`;
- HTTP/auth: `packages/python/ac_platform/http/admin_learning.py`,
  `packages/python/ac_platform/http/auth.py`;
- UI: `apps/admin-web/app/studio/`,
  `apps/admin-web/app/components/studio/studio-runtime.tsx`,
  `apps/admin-web/app/components/admin-shell.tsx`,
  `apps/admin-web/app/lib/admin-api.ts`, and the exact-method/UUID local staging
  bridge allowlist in `apps/admin-web/app/lib/dev-api-proxy.ts`;
- tests: `tests/unit/catalog/test_services.py`,
  `tests/unit/http/test_admin_learning_routes.py`,
  `tests/unit/http/test_app_composition.py`, `tests/database/test_catalog.py`,
  `tests/integration/test_admin_learning_http_postgresql.py`, and the
  admin-web Vitest files.

## Remaining release gates

This evidence does not claim a staging or production release. Before
promotion, run the PostgreSQL integration tests against a disposable database,
apply the candidate migration through the normal release controller, and
capture authenticated desktop/mobile screenshots plus API/audit/ledger proof
from the exact deployed artifact. Assessment review queues, learner diagnosis,
AI scoring, real-call processing, B2B controls, native applications and tenant
billing remain outside this slice.
