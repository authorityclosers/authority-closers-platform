# Scoped Studio draft authoring — local implementation evidence

Implemented four authenticated commands beneath `/v1/admin/studio/program-versions/{version_id}`:

- `POST /modules` with `{title}`;
- `PATCH /modules/{module_id}` with `{title}`;
- `POST /modules/{module_id}/activities` with `{kind,title,prompt,is_required}`;
- `PATCH /activities/{activity_id}` with `{title,prompt}`.

All require the exact whole-version `If-Match` ETag and a caller-retained bounded
`Idempotency-Key`. The response is `{program,resource_id,replayed}`: current
`StudioProgramDetailResponse`, original affected resource identity, and replay flag.
An old successful replay includes its addressed version even beyond the normal
immutable history page. Current content may differ from the original command.

Module title is 1–200 characters; activity title 1–240; prompt is null or 1–2000.
Text is trimmed and blank text rejected. Activity creation explicitly supplies
the existing five-kind taxonomy and boolean required state. Append ordering uses
the existing positive next position. Editing cannot reorder, change kinds,
requirements, prerequisites, scope, provenance or publication policy.

The HTTP boundary requires independent exact `catalog_read` and `catalog_write`
because it returns full Studio detail. The catalog application rechecks persisted
write authority, serializes Person then Program then ProgramVersion, and validates
the current ETag before child changes. Published/superseded children remain
immutable. Revoked assignments cannot replay old successes. Changed intent under
one key conflicts; a stale different command returns 412.

New migration `20260908_0022` follows `20260908_0021`. Its dedicated immutable
`catalog_authoring_commands` receipt stores only key/request digests, operation,
resource IDs and audit linkage, with membership and tenant/version composite FKs.
Receipt, content and canonical append-only audit share one transaction. Audits
contain operation/program/resource IDs, never titles, prompts or raw keys. Exact
new HTTP dependencies commit before emitting a success response. No review
provenance is stamped or cleared; changed content fails the existing review digest.

## Checks actually run

- New relational HTTP suite: **24 passed**. Covers all commands, exact replay,
  subsequent edits/publication replay, stale writes, independently missing read
  or write, revoked write, wrong-program/tenant/global targets, immutable content,
  strict payloads, Origin, audit failure and ASGI commit-refusal rollback.
- New real PostgreSQL suite: **5 passed** in 9.95s on the final schema. It observes
  `pg_blocking_pids` before releasing the winner for stale competing writers,
  same-key append replay, publication-first and authoring-first races. It checks
  exact receipt/audit/content counts, audit chain, rollback and SQL-trigger
  immutability. Uses the existing loopback-only isolated-schema harness and
  `AC_MEDIA_DELIVERY_RENEWAL_POSTGRES_TEST_URL`; each run migrates and removes only
  its fresh random test schema, never runtime/public tables.
- Final combined catalog/admin HTTP/database/composition regressions:
  **173 passed** in 27.82s, including the final HTTP cases and receipt composite FK.
- Final scoped Ruff lint/format and `git diff --check`: passed.
- Final complete Python application mypy: **156 files clean**.
- Alembic reports one head: `20260908_0022`.

No runtime migration, API/browser restart, seed/account/content mutation, Git
commit, remote operation or deployment was performed by this slice. These tests
are not an independent-review or deployed acceptance certificate. The required
three-app/host separation, migration/release approval and exact deployed browser
acceptance remain separate gates. Covers, arbitrary video uploads, draft media
bindings and new content-review policy are not implemented here.

## Revision addendum — 2026-09-09

The published-to-draft revision slice adds `POST
/v1/admin/studio/program-versions/{version_id}/revision` with a strict empty
`{}` body. It requires the current published source's exact `If-Match` ETag and
a bounded `Idempotency-Key`, then freshly rechecks tenant-scoped
`catalog_read` and `catalog_write` authority. Stable person/program locks
serialize the operation; the revision, durable receipt and append-only audit
commit atomically, while exact retries return the original receipt.

The operation is content-only: it creates a new draft and new module/activity
identities, remaps prerequisite edges, preserves source lineage, and clears
review state for the new review cycle. Media bindings, enrollments and progress
are not copied.

### Validation and runtime boundary

- Root's Node 24 frontend checks passed: **232 tests across five files**,
  including **48 editor tests**. Admin/Coach TypeScript checks and scoped lint
  passed.
- Backend checks reported **276 combined passing**, including **10 real
  PostgreSQL checks**; mypy reported **166 files clean**. Migration parity was
  **272 passed, 9 skipped**. Independent review left no Critical/Important
  finding after the unknown-receipt/auth-retry fix.
- Before applying migration `20260909_0023`, the local backup contained 804
  entries and 609,973 bytes, SHA-256
  `826FFFCDFA0D1C913047FD209DA4B2A576ED2CCCC3CDE71F746F8E1EECD06C12`.
  Migration `20260909_0023` was applied. The API initially failed because
  PowerShell left empty `PG*` environment entries instead of removing them;
  the unchanged sandbox guard correctly rejected their presence. Actual
  environment removal restored readiness to HTTP 200 under PID 19452, without
  reseeding or changing sandbox state. The launcher/seed suite reported
  **38 tests passed**, including child-process sanitation and parent restoration.
- Browser revision acceptance remains pending. No deployment was performed.
  Read-only SSH now verifies staging at application release
  `a5eef0df4b340070ac6e58f9912d73a3bf1d2f18`; no production release identity
  was verified. This addendum is implementation/runtime evidence only and does
  not close release gates.

### Local browser handoff

The existing disposable Chrome profile on port 9327 was retained. Its preview
helper now signs into three separate app origins with the existing sealed local
test credential: Learner at `learner.localhost:3100/home`, Platform Admin at
`admin.localhost:3101/` using the operations tenant, and Coach at
`coach.localhost:3102/studio/programs` using the academy tenant. All three normal
sign-ins returned `/v1/me` 200. Rendered checks found the learner welcome and
learning cards, Admin organization overview, and Coach program list. No accounts,
grants, course content or passwords were changed. Three retained in-app browser
tabs were also opened; these separate browser sessions remain at sign-in.
The preview helper has 24 offline regressions; the combined browser, launcher
and local seed suite passed all 62 cases. Scoped Ruff/format and whitespace checks
passed. Review hardened the identity probe with `max_redirects=0`; per-tab
interception is detached on success or failure, without closing user tabs.

The known synthetic Studio course currently contains only draft v1, so this
browser handoff does not establish published-to-revision acceptance. No course
was published just to manufacture that evidence.
