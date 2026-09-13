# Admin conversation review UI

## Scope

This slice adds the reviewer-facing route at `/sales-xray/review/[assignmentId]`.
It uses the existing Admin shell and keeps review management behind the current
server-owned admin boundary. The route presents the bounded journey for an
assigned report:

- server cursor and queue loading/error/retry states;
- timestamped private clip playback boundary;
- Dipak and Suyash reviewer selectors plus Sales, Technical, and UX lenses;
- factual correction/feedback and confidence draft fields;
- append-only audit evidence requirements.

The controls do not assert a report, reviewer identity, clip URL, permission,
or saved event until the Sales-owned assignment/read/submit DTO is available.
The invitation control is disabled and cannot grant `admin_surface`.

## Evidence

- Browser proof: [20260913_ADMIN_REVIEW_UI_BROWSER.png](./20260913_ADMIN_REVIEW_UI_BROWSER.png)
- Route exercised with a QA-authenticated session fixture at
  `http://127.0.0.1:3001/sales-xray/review/assignment-7`.
- The real same-origin review request returned HTTP 404 in this branch, and the
  UI showed the retryable bridge boundary without fabricating a successful
  report or save.

## Validation

- `pnpm --filter @ac/admin-web test -- app/sales-xray/review/review-api.test.ts app/sales-xray/review/review-workspace.test.tsx`
- `pnpm --filter @ac/admin-web exec tsc --noEmit --pretty false`
- Playwright browser proof via `webapp-testing/scripts/with_server.py`.

The Admin lint command is currently blocked by the isolated worktree's missing
`@typescript-eslint/utils` package; this is an environment dependency issue and
does not change the route implementation.
