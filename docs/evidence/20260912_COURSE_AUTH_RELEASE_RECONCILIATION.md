# Course authentication release reconciliation — 2026-09-12

Status: authentication checks passed; standalone acceptance remains unproved.
No publication, deployment, real OAuth provider acceptance or completed
email/new-device journey is claimed.

## Source and preservation

Release base: `c278cf6233072526b606631829bcc330a113b60c`.
Course checkpoint: `dc4b2a7216651697762417aef5fb14f358099e08`, whose sole parent
is `edb6ea903a4374f3286f333affea12bf795ced40`.
The integration branch is `codex/course-auth-release-20260912`.

Independent comparison found all 24 source paths in c278 identical to their
edb6 bases, including absence of the five additions. Applying only the single
dc4 commit delta therefore preserved every other c278 path. The index and raw
working bytes for all 24 files were verified against the source manifest,
including Git mode, blob ID, SHA-256 and byte count. The source tree and
later dirty UI work were not copied or reset.

The immutable object inventory SHA-256 is
`6d043839d37dfc04a327032f91a32b3c4cad0f22d3ec01b994ccc87b02e8062d`;
browser binding SHA-256 is
`8b86108252d0a9330e054f892a000e70724398314b1bde1602686847adf47f65`.
The new staged-integration receipt is
`course-auth-integration-staged-20260912.json`, SHA-256
`8894dec2fb681de5148b5583e94af0d638a2bf3a9d9a377ee384c49ece073b0b`.
All are in the external recovery packet. This document is the sole additional
integration-evidence path beyond the 24 source paths.

## Behavior and review

The existing free-course selection survives password and signed Google
navigation, recoverable consent/account outcomes, expired sessions and
onboarding. Only the known scalar course identifier is accepted; navigation
targets remain fixed local routes. Enrollment remains an explicit existing
server operation. Registration requires client readiness, POST for passwords
and explicit consent. Cookie, session, membership and access boundaries remain
unchanged.

Independent auth/security review found no actionable P0/P1/P2 issues in the
bounded diff. Independent integration review verified all 24 object identities
and all 16 recorded browser runtime source hashes. The six historical PNGs
exist with their recorded viewport widths; their original receipt did not
record image-content hashes, so historical image-byte identity is not proved.
They are not target-release deployment screenshots.

## Validation boundary

Source-owner evidence reports 1,578 learner tests across 87 files, 209 focused
frontend tests, 77 Python auth tests, static checks and synthetic browser
journeys. The three Google browser tests intercept the start request with
HTTP 204; they do not establish provider acceptance. Detailed original results
and retained failures remain in `20260911_FREE_COURSE_AUTH_CONTINUITY.md`.

Root independently installed all 399 locked packages offline with Node 24.19.0
and pnpm 11.19.0. Dependency manifests and the lockfile were unchanged; the
original UI worktree's workspace links were not reused. Final root results:

- All 1,578 learner tests passed across 87 files, using one Vitest worker.
- 167 shared Python authentication/transaction/Coach-surface tests passed.
  One existing Starlette/httpx deprecation warning remains.
- All 16 Admin/Coach operations-login tests passed.
- Scoped Ruff lint/format and auth mypy, fresh Next route type generation,
  learner typecheck, full learner lint and all 20 changed frontend files'
  Prettier checks passed.
- A fresh Next 16.3.3 production build passed, including its TypeScript check
  and all 26 static pages. The build used one page worker and a 2 GiB Node heap
  limit to respect the shared machine's capacity; application configuration
  was unchanged. Generated Next declarations were retained as validation
  evidence, then the tracked generated file was restored to its original bytes.
- All three registration browser cases passed against that root build on
  loopback port 3181. A fresh JUnit report confirmed exactly three passing
  cases and no skips/errors/failures. All 24 bound source hashes were unchanged
  through the run, and the owned server exited with its listener removed.
  This used `next start`; Docker's standalone packaging is a separate gate.

A subsequent startup of the generated standalone server failed before browser
tests ran: Node reported Windows `EPERM` while resolving the generated React
symlink beneath the standalone pnpm tree. The target directory exists. This
does not invalidate the completed auth regressions, but standalone acceptance
is not passing. No source, dependency, ACL or generated link was altered to
work around the error. The failed run is retained in
`course-auth-root-standalone-20260912T183119Z`; its conservative cleanup flag
is false because pytest never completed. A separate read-only check confirmed
the owned server PID 21720 had exited and port 3181 had no listener. The exact
Windows link cause and Linux immutable-image acceptance remain separate checks.

Root logs are `course-auth-root-install-20260912.log`,
`course-auth-root-learner-tests-20260912.log`,
`course-auth-root-static-20260912T182437Z`,
`course-auth-root-build-20260912.log` and
`course-auth-root-browser-20260912T182828Z` in the recovery packet.
The packet-local browser runner also requires the expected 24-path staged
scope, a free dedicated port, bounded readiness and an exact fresh test count.
It leaves timeout cleanup unverified if the browser test process does not
complete normally. The completed run's cleanup check passed.

Current application CI does not set the browser URL or provision Chromium,
so its ordinary pytest run skips these three opt-in browser cases. A required
production-served browser gate is an explicit follow-up, not implied by green
existing CI. No actual Google provider, email or account-creation journey is
proved by the intercepted Google-start response.

Exact combined CI, immutable artifacts, recovery and role gates, target-release
authenticated staging/screenshots and governed production acceptance remain
outstanding. The earlier scanner/backup external-action approval requests
remain separate from this local integration. The subsequent three-path mobile
checkpoint is independently reviewed but excluded from this authentication
commit; it will retain its own integration boundary.
