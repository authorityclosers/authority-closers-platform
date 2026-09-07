# Alpha dashboard core and plan loading — 2026-09-07

Status: implemented in the consolidation worktree; focused verification passed.
Base commit: `4aee7dd238136839236ed8dac81906467f65862b`.
This record describes an uncommitted local candidate, not a staged release.

## Result and interface

The `/home` route mounts `DashboardRuntime`. Its core dashboard previously waited
for the optional calendar request to finish. It now renders the server-authorized
core and primary activity action while the plan panel has its own truthful loading
state. A delayed calendar response does not hold the entire dashboard skeleton.

- `loadDashboardCoreData(api, signal)` retains identity, membership, onboarding,
  published catalog and learning-projection ordering, errors and offline metadata.
- `loadDashboardPlan(api, me, signal)` returns the optional typed plan result.
- `loadDashboardData(api, signal)` remains a compatibility wrapper returning both
  settled reads for existing consumers and direct-loader tests.
- The mounted runtime loads the plan after the core prerequisites pass. Plan
  loading is independent of the primary task; it is not speculative prefetch.

No calendar/catalog request bypasses the onboarding prerequisite in the runtime.
No calendar request is made without membership and a selected tenant. A current
calendar 401 still replaces the dashboard with session recovery; other optional
failures remain in the plan panel. Plan callbacks share the core load's abort
signal and generation guards, including inside the state updater, so superseded
or unmounted results cannot replace the current dashboard.

No artwork, styles, published content, progress rules, endpoint, telemetry,
business state, backend mutation or dirty `direction-a-shell.test.ts` content
was changed by this slice.

## Verification

Environment: Windows, bundled Node.js `v24.19.0`, bundled pnpm command shim,
Vitest `4.1.11`, actual `DashboardRuntime` mounted under Happy DOM.

- Four focused test files: **69 tests passed** (`dashboard-runtime.test.tsx`,
  `direction-a-shell.test.ts`, `learner-performance.test.ts`,
  `learner-runtime-concurrency.test.ts`). The existing dirty test file was run
  without editing it.
- Nine dedicated tests cover deferred onboarding/plan behavior with the primary
  link usable before plan resolution, plan-only failure, current-session 401,
  stale tenant success and stale 401 despite an abort-ignoring test API, unmount
  cancellation, and complete-loader compatibility/no-tenant/onboarding gates.
- The new nine-test file passed again after correcting a fixture's TypeScript
  literal annotation. Learner `tsc --noEmit --incremental false` passed.
- Targeted ESLint passed with zero warnings; formatting and diff whitespace
  checks passed for the changed implementation/test files.

Focused regression command with the bundled Node directory first on process PATH:

```text
pnpm --filter @ac/learner-web exec vitest run app/components/dashboard-runtime.test.tsx app/lib/direction-a-shell.test.ts app/lib/learner-performance.test.ts app/components/learner-runtime-concurrency.test.ts
```

## Measurement and release limits

The deferred-promise test establishes an ordering property: the primary dashboard
action is present while the plan promise is still unresolved. It does not claim
a measured millisecond improvement, field Web Vitals, or authenticated staging
performance. The integrated candidate still needs its production-build browser
comparison, responsive plan-state inspection, exact-release review and normal
release gates. No full build, server restart, commit or deployment was performed
for this slice.
