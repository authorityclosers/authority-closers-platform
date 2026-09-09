# Coach workspace staging candidate — 10 September 2026

Status: clean candidate prepared from exact base `7bdd069d4bf00561edcab90b1679666205708185`. It is not deployed and is not production acceptance.

## Capability boundary

This candidate adds the persistent Coach workspace shell and the Dashboard, Courses, Publication and Settings destinations. It reads existing canonical Studio projections and keeps existing course-editor behavior. It does not add course creation, schema migrations, video upload, media storage, provider activation, publishing shortcuts or new authority.

The route-to-component path is:

- `/studio` → `StudioDashboard`
- `/studio/programs` → existing `StudioProgramList`
- `/studio/programs/[programId]` → existing `StudioProgram`
- `/studio/publication` → `StudioPublicationQueue`
- `/studio/settings` → `CoachSettings`
- `/studio/layout.tsx` → one persistent `CoachShell` around all Studio routes

The outer Coach shell maps the Operations palette into the shared `@ac/ui`
theme contract. This prevents the dashboard learning symbol from falling back
to invalid/black fills and keeps it responsive to light, dark and system mode.

Session checks remain server-authoritative. Route and focus/visibility revalidation hide and inert the last verified private tree while checking, retain same-session form state after a retryable outage or bounded total-request timeout, and discard it after a definitive denial or confirmed identity/session/tenant change. The three session reads share one abort signal; forced refresh, route change, timeout and unmount cancel obsolete work. HTTP 401/403 is denied; network, timeout and 5xx failures remain retryable.

## Exact source manifest

Whole-file Coach UI delta:

- `apps/coach-web/app/components/coach-shell.tsx`
- `apps/coach-web/app/components/coach-preferences.tsx`
- `apps/coach-web/app/components/coach-settings.tsx`
- `apps/coach-web/app/components/coach-workspace.test.tsx`
- `apps/coach-web/app/layout.tsx`
- `apps/coach-web/app/page.tsx`
- `apps/coach-web/app/studio/layout.tsx`
- `apps/coach-web/app/studio/page.tsx`
- `apps/coach-web/app/studio/programs/page.tsx`
- `apps/coach-web/app/studio/programs/[programId]/page.tsx`
- `apps/coach-web/app/studio/publication/page.tsx`
- `apps/coach-web/app/studio/settings/page.tsx`
- `apps/coach-web/app/styles.css`
- `apps/coach-web/vitest.config.mjs`
- `packages/typescript/operations-web/src/studio/studio-workspace.tsx`
- `packages/typescript/operations-web/src/studio/studio-workspace.module.css`

Shared operations delta:

- `packages/typescript/operations-web/package.json`: exports the workspace module.
- `packages/typescript/operations-web/src/admin-api.ts`: distinguishes definitive session denial from retryable transport/server failure.
- `packages/typescript/operations-web/src/admin-session.tsx`: opt-in route/focus revalidation and private-tree preservation.
- `packages/typescript/operations-web/src/operations-login.tsx`: sends a successful Coach sign-in to the dashboard.
- `packages/typescript/operations-web/src/studio/studio-runtime.tsx`: exports the existing loader/boundary, rejects cross-tenant payloads and provides learner-facing recovery copy.
- `apps/admin-web/app/lib/admin-api.test.ts`
- `apps/admin-web/app/components/admin-session-refresh.test.tsx`
- `apps/admin-web/app/components/operations-login.test.tsx`

Explicit exclusions: every database migration; course-create API/UI; Studio video API/panel/editor changes; media, storage, scanner, probe, outbox and worker changes; provider activation; development-proxy or Coach HTTP allowlist expansion.

## Acceptance evidence

Environment: Windows clean worktree, Node `24.19.0`, pnpm `11.19.0`, `NODE_OPTIONS=--max-old-space-size=768`. Builds ran sequentially.

| Check                              | Observed result                                      | Status  |
| ---------------------------------- | ---------------------------------------------------- | ------- |
| Coach TypeScript                   | `tsc --noEmit`                                       | pass    |
| Coach ESLint                       | zero warnings                                        | pass    |
| Coach component suite              | 1 file, 14 tests                                     | pass    |
| Coach production build             | 8 routes emitted, including four Studio destinations | pass    |
| Admin TypeScript                   | `tsc --noEmit`                                       | pass    |
| Admin ESLint                       | zero warnings                                        | pass    |
| Admin focused session/API/login    | 3 files, 124 tests                                   | pass    |
| Admin full suite                   | 18 files, 433 tests                                  | pass    |
| Admin production build             | 12 routes emitted                                    | pass    |
| Coach HTTP surface regression      | 71 tests; one dependency deprecation warning         | pass    |
| Prettier                           | candidate TypeScript, CSS, JSON and evidence         | pass    |
| Exact-candidate browser acceptance | authenticated desktop/mobile/light/dark/focus routes | pending |

Commit `0dbcc74` was separately exercised in an isolated synthetic Coach login: 16 screenshots across 1440/390 and light/dark, correct active routes, no overflow/off-viewport actions, corrected shared-symbol fills and zero console issues. Evidence is in `.tmp/local-platform/coach-isolated-acceptance-20260910-021438-837595/proof.json`. That predecessor evidence is not substituted for an exact amended-candidate browser retest.

## Deferred work

Course creation follows only after the reviewed `0024`/`0025` backup, restore-proof and restore-drill migration catalogue update. Real video storage remains separately gated. Production identity, secrets, legacy DNS and action-time approval remain production gates and do not block this staging-only UI candidate.
