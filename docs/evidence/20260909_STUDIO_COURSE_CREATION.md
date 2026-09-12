# Studio course creation — local implementation evidence

Date: 2026-09-09. Implementation tree: `C:\Users\Suyash\.codex\worktrees\d2de\authority-closers-platform`.

This note records the current local working-tree implementation and bounded
browser checks only. It excludes the exact committed baseline
`7bdd069d4bf00561edcab90b1679666205708185` and unrelated working-tree scope.
No production, staging, publication, learner-visibility, or deployment claim is
made here.

## Course-creation behavior

- `POST /v1/admin/studio/programs` accepts the bounded title command only and
  requires tenant-wide `catalog_read` plus `catalog_write` through the normal
  session/context path. The command atomically creates one tenant course and
  its empty draft version, records idempotency/audit state, and does not infer
  provenance, publish, enrollment, media, or learner access.
- The implementation path is
  `packages/python/ac_platform/catalog/services.py` (`create_program_draft`),
  `packages/python/ac_platform/http/admin_learning.py`, and the Coach/Admin
  surface allowlist. The focused creation fixture is
  `tests/unit/http/test_studio_course_creation.py`.
- Replay and rollback coverage includes fresh capability revocation and outer
  commit failure. PostgreSQL coverage includes same-key replay, two distinct
  creations for different keys, and the concurrent conflicting-intent race.

## Verification evidence

| Check | Result |
| --- | --- |
| New HTTP course-creation checks | 32 passed; includes fresh revocation and commit-failure coverage |
| PostgreSQL course-creation race checks | 3 passed; same key, different key, and conflict race |
| Catalog/HTTP regression suite | 242 passed |
| Admin tests | 465 passed across 19 files, including 8 course-create component tests |
| Admin + Coach TypeScript | Passed |
| Ruff | Passed for the changed course-creation Python files |
| Scoped ESLint | Passed; warning limited to Pages |
| Review follow-up | Late A/B recovery finding fixed; follow-up clean |

These are local implementation/test results supplied by the release worktree;
they do not authorize production use or replace normal server-side authority.

## Browser gate results

### Coach session

On `http://coach.localhost:3102/studio/programs`, the rendered accessible
controls were only “Skip to content”, “Academy Studio by Cohorva”, “Courses”,
“Sign out”, and “Open course”. There was no “Create course” control, no form,
and zero inputs.

Normal same-origin `GET /v1/me/studio-access` returned 200 with only these
capabilities, all `scope_kind=program`, for
`a980466f-9152-57df-ac31-6bb9ab5f0471`: `catalog_read`, `catalog_write`, and
`catalog_publish`. There was no tenant-scoped read/write capability. This is the
expected UI gate: `studio-course-create.tsx` requires both permissions without
a program id, while `admin-session.tsx` accepts program scope only when a
program is explicitly supplied.

Responsive/theme captures of the blocked state found no horizontal overflow:

- 320px: scroll width 305, viewport width 320.
- 390px: scroll width 390, viewport width 390.
- 1440px: scroll width 1440, viewport width 1440.
- Same results in light and dark modes.

### Admin session

Using a fresh direct-CDP target at
`http://admin.localhost:3101/studio/programs`, the page rendered HTTP 500
“Internal Server Error” with no title, controls, inputs, or session projection.
The same 500 occurred for `/`, `/login`, `/studio`, `/people`, `/v1/me`,
`/v1/context`, and `/v1/me/studio-access`. Therefore Admin academy authority
could not be evaluated and no course creation was attempted; no privilege was
assigned or inferred.

Artifacts from the bounded direct-CDP check:

- [Coach JSON](../../.tmp/local-platform/new/course-create-qa-20260909/course-create-qa.json)
- [Admin JSON](../../.tmp/local-platform/new/course-create-qa-20260909/admin-course-create-qa.json)
- Coach captures: `programs-blocked-{light,dark}-{320,390,1440}.png` in the same directory.
- Admin captures: `admin-programs-blocked-{light,dark}-{320,390,1440}.png` in the same directory.

Playwright `connect_over_cdp` timed out after the websocket handshake; direct
single-target CDP was used without reading cookies or tokens. Existing Coach
and Learner pages were preserved. The synthetic title
`LOCAL QA — Course creation 20260909` was not submitted.

## Remaining boundary

The normal tenant-authorized Admin page must be healthy before the visible
create-form, save-to-`Add first module`, and reload-persistence checks can run.
Normal video upload/processing, media selection/binding, publication, and the
local Big Buck Bunny playback fixture remain separate and were not uploaded or
attached to a course in this check.

## Backup parity dependency

The reviewed `20260909_0024` media-library-index and `20260909_0025`
course-creation migrations add no canonical tables. The backup writer, Restic
restore proof, and application restore drill therefore accept both exact heads
under the existing 53-table `ac-postgres-parity-v5` contract; `20260910_0026`
remains unapproved and rejected. Local parity and focused restore-proof checks
passed after this catalogue update. The broader source restore-drill fixture
currently resolves the unapproved 0026 working-tree head and remains outside
this approval. No installer rollout or environment deployment was performed.
