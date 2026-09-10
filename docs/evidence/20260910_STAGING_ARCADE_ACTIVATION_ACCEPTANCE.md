# Staging Arcade activation — 2026-09-10

## Released, not merely packaged

- Exact immutable release: `4e8d413b828ab750d7c5e20d1a9320d0f427c823`.
- Previous staging release: `74631e0dd94a1d54a2e2b88bc925e47e0e0c7029`.
- Packaging workflow [34433967416](https://github.com/authorityclosers/authority-closers-platform/actions/runs/34433967416): all three jobs succeeded.
- Artifact `10135862922`, `ac-application-4e8d413b828ab750d7c5e20d1a9320d0f427c823`, 192110650 bytes; API digest `sha256:d3bfcb5747aac6160dad09c96bf2f0af4e732cd0663d636a24de6cc7028a631a`.
- Canonical Windows controller: `scripts/Deploy-Staging.ps1 -ReleaseSha 4e8d413b828ab750d7c5e20d1a9320d0f427c823 -TargetEnvironment staging`; completed with exit 0. No manual environment override or operational SQL.
- Independent SSH read confirmed `current-staging` points to the exact release. Committed receipt: `/srv/authority-closers/application/deployments/staging/20260910T040226Z-4e8d413b828ab750d7c5e20d1a9320d0f427c823-bGuRZi.env`; status `COMMITTED`, migration `20260910_0027`.

## Live acceptance at approximately 04:03 UTC

| Check | Result |
| --- | --- |
| Learner `/`, `/healthz`, app icons, service worker | 200; controller routing checks passed |
| Coach `/login`, unauthenticated private root | 200 login; normal same-host sign-in required |
| Admin public route | Expected Cloudflare Access boundary; not an authenticated admin journey |
| API liveness/readiness/catalog | 200; exact release checked by controller |
| API documentation endpoints | 404, as required |
| Google OAuth start | Cookie and exact-callback checks passed; not a completed Google login |
| Learner `/practice/availability` | 200, `{"enabled":true}`, `no-store, private` |
| API runtime pilot scope (booleans only) | Enabled; pilot matches public learner tenant; pilot differs from operations tenant; all three true, no identifiers or secrets printed |
| Learner `/practice`, `/profile` | 200, private/no-store |
| Private `/v1/practice/sets`, `/v1/community/profile`, `/v1/community/leaderboard` | 401 and no-store without a session |
| Controlled in-app browser `/practice` | Loaded the normal “Sign in to open Practice Arcade” state; no longer a 404 |
| Containers (independent coordinator check) | PostgreSQL, API, Learner, Admin, Coach healthy; worker running |
| WordPress apex and www | Controller preservation checks passed; unchanged |
| Production | No `current-production` release; no production deployment performed |

This makes the already packaged colourful Arcade presentation and approved earned-only tenant pilot available on staging. Username claiming and the explicit opt-in, all-time canonical-practice-XP leaderboard were packaged in the previous release and remain private APIs. Do not describe the above signed-out checks as a real learner claiming a username, opting in, completing a run, or receiving a reward on the VPS.

## Supporting verification and limitations

- Release/settings/pilot/HTTP checks: 358 passed, 6 skipped; adjacent controller/transport/public-film checks: 109 passed, 8 skipped; archive checks: 56 passed. Skips reflect unavailable local POSIX/Caddy/Linux Docker surfaces, not remote acceptance.
- Independent Node 24 focused Arcade/navigation/community verification: 107 passed; Python community policy/application/HTTP: 50 passed.
- Root actual isolated PostgreSQL community integration: `tests/integration/test_community_identity_postgresql.py`, 7 passed in 12.90 seconds. This used only the disposable local database.
- The preceding isolated off-site restore proof is recorded in `20260910_STAGING_OFFSITE_RESTORE_ACCEPTANCE.md`. Historical failed attempts remain preserved.
- Production configuration and exact Google provider callbacks are still missing. Production policy/consent and deployment acceptance are not waived by this staging release.
- New Coach upload/processing/library integration is tested locally but is not included in this immutable release. Operational upload-to-publication-to-authorized-learner playback, real long/4K acceptance and production promotion remain separate unfinished work.

## Local follow-up, not part of the deployed artifact

Independent review found that the Arcade username shortcut could arrive before the asynchronous Profile card existed. Root added two regression tests that failed before the fix, then implemented exact-fragment mount/hash-navigation scrolling and keyboard focus, with no focus theft on ordinary visits or API refresh, no smooth motion, and listener cleanup. The focused identity/Arcade/shell run passed 38 tests. Adding Profile-runtime coverage exposed an asynchronous hash-event test-isolation issue; scoped `location.hash` mocks resolved it without serializing tests or weakening assertions. The final default-parallel four-file run passed 51 tests, independently repeated with no remaining findings. Learner typecheck, targeted ESLint, Prettier and diff whitespace checks passed. This subsequent three-file UI correction remains local pending release; do not attribute it to `4e8d413`.

At approximately 04:14 UTC, final production Learner/Coach/API public probes still returned503. The prior production hold is unchanged, not a regression caused by the staging deployment.
