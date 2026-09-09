# Independent Coach HTTP surface — local source verification

Date: 2026-09-08. Worktree: `C:\Users\Suyash\.codex\worktrees\d2de\authority-closers-platform`.

## Implemented boundary

`AC_COACH_APP_URL` is an exact distinct-host origin. Default local value is
`http://coach.localhost:3102`; staging/production default to the exact configured
environment's `https://coach-staging.authorityclosers.com` and
`https://coach.authorityclosers.com`. Existing deployment profiles can omit the
new setting during the app split. No wildcard, credential, path, query or fragment
is accepted. New learner origins `learner[-staging].authorityclosers.com` are
accepted alongside the old `app.authorityclosers.com` / `staging.authorityclosers.com`
configuration choices during cutover; only the selected origin is trusted.

Coach admission is a default-deny HTTP method/path inventory: normal existing
password login/recovery/reset/logout, Google start/callback, self `/me` and Studio
scope projection, context selection, self session revocation, existing Studio
read/draft-author/publish routes, and health. Registration/verification/onboarding,
learner workflows, platform operations and future media commands are not exposed
there. The existing Admin-only guard is unchanged. A separate Studio router admits
Admin or Coach but retains every canonical session, selected-tenant, scoped
capability, Origin, concurrency, audit and transaction check.

Google uses signed `surface=coach` with the exact Coach callback and same-surface
return path; only authentication/linking of existing identities is allowed, not
self-registration. Cookies remain host-only; identities and password recovery are
the same backend services, not copied accounts, roles, or cross-host cookies.
Origin/Host matching is required for Coach even in the local bridge; forwarded
host headers do not select a surface. Strict `/me` and `/context` DTOs are unchanged.

## Checks actually run

- Combined Settings, auth transactions/routes, Coach boundary, relational Studio
  scope and draft authoring, admin routes, and app composition: **416 passed** in
  23.44s. All 24 authoring scenarios run on both Admin and Coach, including actual
  relational save/replay/revocation/rollback. Coach publish/read scope tests also
  retain learner membership and reject unassigned programs.
- HTTP boundary and rate-limit regressions: **24 passed** in 2.79s.
- Complete Python mypy: **157 source files clean**.
- Scoped Ruff lint, format check (11 files) and `git diff --check`: passed.
- Independent review found and corrected a local/development wildcard-host gap.
  The validator now explicitly refuses `*` or absent hostnames. Six added tests
  cover local/test/development; the complete Coach suite is **66 passed**, also
  independently rerun by the reviewer. No remaining Critical/Important finding.

No database migration, runtime restart, seed/account mutation, provider request,
remote setting change, Git commit or deployment was performed by this slice.
Deployment still requires the separate Coach app/proxy and explicitly registered
Google callback URI for the selected Coach origin. This source evidence is not a
deployed-browser or provider-configuration acceptance claim.
