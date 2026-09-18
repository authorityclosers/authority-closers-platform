# Admin People session invalidation evidence

## Scope

The Admin People read surface now invalidates the shared admin session when a
lookup or diagnosis request returns HTTP 401 or 403. The invalidation is
scoped to the tenant, person, and session identity that issued the request.
It clears the confirmed provider session through the existing session context,
so the shared header, tenant context, navigation, and route boundary update
together. People still clears its private learner records and shows the
sign-in recovery message. No browser globals or cross-tab events are used.

## Regression coverage

The real `AdminSessionProvider` and `AdminSessionStatus` test confirms that a
stale invalidator captured before a new session is verified cannot invalidate
the new identity, while an invalidator for the current identity changes the
header to the denied state and removes private content.

The People runtime test mounts the real `AdminShell` and provider. It exercises
both 401 and 403 diagnosis failures and verifies the denied header, missing
verified tenant context, sign-in route boundary, and cleared learner data.

Validation from the admin workspace:

```text
pnpm exec vitest run app/components/people-runtime.test.tsx app/components/admin-session-refresh.test.tsx
37 passed

pnpm exec prettier --check ../../packages/typescript/operations-web/src/admin-session.tsx app/components/people-runtime.tsx app/components/people-runtime.test.tsx app/components/admin-session-refresh.test.tsx
All matched files use Prettier code style.

pnpm exec tsc --noEmit
passed
```

The additional in-flight regression starts a refresh, invalidates its current
identity, confirms its signal is aborted, then resolves the old response and
verifies it cannot restore the private tree. Main reran the final source under
supported Node 24: 37 Admin tests and 40 Coach regression tests passed. Main
source review found no remaining actionable defect in this bounded change.
Logs: external recovery packet `admin-people-validation/session-node24-tests.log`
and `session-coach-node24-tests.log`. Canonical browser rerun follows this source
checkpoint; no deployment acceptance is claimed here.
