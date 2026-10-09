# AUT-1350: server-built dashboard checkpoint

Base `4c76de1c69e7edc77f36486dbf347d2bdfc0b862`; branch `task/sx-shell/1350-server-dashboard`.
Authority: CEO strike brief revision `2c43e685-2175-42a6-bff0-71635b1092c9`.

Read-only bootstrap composes existing identity/directory/profile services without selection or renewal.
The bounded dashboard uses existing permission, canonical allowance, activity and saved-call services.
Five recent calls; each part has a two-second timeout and savepoint. AsyncSession reads stay sequential.
Session lives in a route group; policy/sign-in stay outside it. Selected widgets render on the server.
Greeting, charts, recent-call fitting and retry are client islands. The existing browser fallback is retained.
Server GETs use the exact internal origin, incoming cookies, no-store, redirect refusal and a ten-second bound.
Request-local React cache shares bootstrap between page/layout. Owner surfaces and public URLs are preserved.
Bootstrap registers through the existing workspace installer; `http/app.py` stays with open PR #415.

Verified 9 October 2026: existing directory/activity HTTP suites 26 passed; directory and new HTTP suites
30 passed after composition change. Fictional relational tests prove no writes/selection/renewal/cookies,
and session/query/permission/database/timeout negatives. Existing dashboard/session/layout/workspace/owner
screen tests: 47 passed. Revised server HTML, seeded workspace and profile-store suites: 16 passed.
The server-only test harness alias uses Next's bundled empty marker. Route type generation, web TypeScript,
targeted strict mypy, changed-file ESLint, Python Ruff and whitespace checks passed.
Final populated-recent-call/denial HTML and original dashboard suite: 11 passed.

AUT-1646 preview :3036 was inspected before edits: loading skeleton, no populated data claim.
Updated dashboard HTTP 200, 16.009 seconds including dev compilation. New bootstrap HTTP 404,
also with the dev host header. A branch-backed API/UI preview is still required. Authenticated HTML,
browser network acceptance, production build and eager JS before/after budget are unverified; dev JS
is not a production budget. No release, data/provider activation or production operation occurred.

Exact manifest IDs were fetched: Master/BRD/IMP-00/01/03/04/05, then all required domain sources and UXA.
Manifest: `docs/workflows/instructor-admin-workflow/01-research-journeys/source-manifest.csv`.
Current owner brief wins over historical August defaults. Windows AC Orchestra skill path unavailable;
no Pro/cloud handoff claimed. Next: Root supplies bounded branch API/UI preview with AUT-63 audit/rollback;
Admin Lead verifies fictional journeys/budget, then CTO review and CEO approval. Release engine closes delivery.
