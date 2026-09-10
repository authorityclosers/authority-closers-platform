# Three-app local acceptance checkpoint

Date: 2026-09-08. This is a verified implementation checkpoint, **not a production release or completion of the Alpha goal**.

## Current application boundary

The latest user direction supersedes earlier acceptance of Studio inside `admin-web`: Learner, Platform Admin and Coach/Academy Studio are now three independently packaged applications sharing canonical backend identity and authorization. Historical evidence remains historical; extraction does not widen capabilities or create an Instructor role.

| Application | Production target | Staging target |
| --- | --- | --- |
| Learner | `learner.authorityclosers.com` | `learner-staging.authorityclosers.com` |
| Platform Admin | `admin.authorityclosers.com` | `admin-staging.authorityclosers.com` |
| Coach / Academy Studio | `coach.authorityclosers.com` | `coach-staging.authorityclosers.com` |

The WordPress apex and `www` are unchanged. Target hostnames are deployment contracts, not evidence that this candidate is serving there.

## Verified snapshot

- Full learner suite: **1,309 passed across 65 files**, 71.83 s, one worker with a 512 MB Node heap. Full learner TypeScript check passed. The stale CSS source-contract test now ignores comments and expects fluid `body { min-width: 0 }`; all root overflow/max-width masking prohibitions remain. Scoped lint and diff checks passed.
- Focused Admin/shared operations suite: **221 passed**; full Admin TypeScript check passed. The subsequent full Admin run passed **327 tests in 18.64 s**, and Coach TypeScript check passed. See [workspace sign-in evidence](20260908_OPERATIONS_WORKSPACE_SIGN_IN.md).
- Parent-run broad Python unit/infra snapshot: **2,089 passed, 24 skipped**, 151.08 s. Skipped cases are not claimed as verified.
- Parent-run operations bootstrap: **62 passed**, 24.62 s: 59 unit/relational cases plus three actual PostgreSQL concurrency/rollback cases in disposable schemas. See [bootstrap evidence](20260908_OPERATIONS_ONLY_BOOTSTRAP.md).

The root's native Chrome Coach layout [proof](screenshots/coach-layout-2026-09-07T23-44-15.696Z/proof.json) records four viewport checks: 320, 390, 768 and 1440 px. It verifies no horizontal overflow, persistent desktop outline, and matching accessible expand/collapse state on narrower layouts. The proof records **zero mutations and zero external requests**. Captures include [320 px collapsed](screenshots/coach-layout-2026-09-07T23-44-15.696Z/editor-320-collapsed.png), [320 px expanded](screenshots/coach-layout-2026-09-07T23-44-15.696Z/editor-320-expanded.png) and [desktop](screenshots/coach-layout-2026-09-07T23-44-15.696Z/editor-1440.png). This layout proof does not itself prove publishing or real-person access.

The root also ran actual VPS Caddy **validate/adapt successfully**. No Caddy reload or candidate deployment occurred. Production identity/capability provisioning, approved content/provider activation, full release acceptance, and screenshot publication to Drive are not established by this checkpoint. No native-app acceptance is claimed.
