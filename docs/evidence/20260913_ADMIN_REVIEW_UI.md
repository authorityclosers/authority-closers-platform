# Admin conversation review UI

## Scope

This slice adds the reviewer-facing route at `/sales-xray/review/[assignmentId]`
to both the Admin app and the Academy app. The shared form lives in
`@ac/sales-xray-review-ui`; Admin keeps queue management behind the current
server-owned admin boundary, while the Academy adapter can render for an
ordinary verified assignment reviewer without `admin_surface`. The route
presents the bounded journey for an assigned report:

- server cursor and queue loading/error/retry states;
- timestamped private clip playback boundary;
- Dipak and Suyash reviewer selectors plus Sales, Technical, and UX lenses;
- factual correction/feedback and confidence draft fields;
- append-only audit evidence requirements.

The controls do not assert a report, reviewer identity, clip URL, permission,
or saved event until the Sales-owned assignment/read/submit DTO is available.
The invitation control is disabled and cannot grant `admin_surface`. Once the
DTO is supplied, the shared form submits the signed-in reviewer identity, exact
clip bounds, lens, feedback, and confidence through an injected server adapter;
failed saves preserve the draft and reuse the same idempotency key.

## Evidence

- Browser proof: [20260913_ADMIN_REVIEW_UI_BROWSER.png](./20260913_ADMIN_REVIEW_UI_BROWSER.png)
- Academy browser proof: [20260913_ACADEMY_REVIEW_UI_BROWSER.png](./20260913_ACADEMY_REVIEW_UI_BROWSER.png)
- Route exercised with a QA-authenticated session fixture at
  `http://127.0.0.1:3001/sales-xray/review/assignment-7`.
- Academy route exercised at
  `http://127.0.0.1:3000/sales-xray/review/assignment-7` with the standard
  `LearnerShell`.
- The Admin route showed the contract-pending boundary without fabricating a
  successful report or save. The Academy route showed the same server-owned
  assignment boundary in the normal learner shell.

## Validation

- `pnpm --filter @ac/admin-web test -- app/sales-xray/review/review-api.test.ts app/sales-xray/review/review-workspace.test.tsx`
- `pnpm --filter @ac/sales-xray-review-ui exec vitest run --passWithNoTests`
- `pnpm --filter @ac/learner-web test -- app/sales-xray/review/review-assignment-adapter.test.tsx`
- `pnpm --filter @ac/admin-web exec tsc --noEmit --pretty false`
- `pnpm --filter @ac/learner-web exec tsc --noEmit --pretty false`
- `pnpm --filter @ac/sales-xray-review-ui typecheck`
- `pnpm --filter @ac/admin-web build`
- `pnpm --filter @ac/learner-web build`
- Playwright browser proof via `webapp-testing/scripts/with_server.py`.

The Admin lint command is currently blocked by the isolated worktree's missing
`@typescript-eslint/utils` package; this is an environment dependency issue and
does not change the route implementation.
