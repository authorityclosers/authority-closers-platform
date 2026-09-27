# Local state workbench and navigation verification

Date: 2026-09-23. Base: 34fa8de99c7ebc0a61cd9ac71bf54b459c6ea990.

## Scope

The development-only review bridge now presents the actual app in a same-origin
canvas, with captured browser states, authorized call progress and direct app
URLs. Previous/next, copy URL, full-screen and mobile-width controls operate on
the same mounted components. Desktop 846x698 and mobile 390x844 navigation keep
the canvas visible in the first viewport. This is not complete synthetic state
coverage: unobserved processing states remain absent. The owner's later fixture
test-mode request is a separate change, not a claim made by this patch.

Browser-local observations retain only bounded allowlisted control metadata,
not audio bytes. They expire in the server store and already-open client frame,
and are invalidated across session/context changes. Invalid replacement files
preserve the earlier valid selected-file name and size as an indivisible pair.
Read-only inspection shows passive verification status and never mounts a live
Turnstile challenge. Real analysis commands remain blocked by the local bridge.

Only local app responses permit SAMEORIGIN framing; API/review surfaces remain
DENY. Production uses the no-op review port, with no development alias. The
explicit empty Turbopack configuration preserves the ordinary production build
while the local review launcher intentionally uses webpack.

## Navigation defect reproduced and repaired

The browser at port 3016 stayed on the upload screen after clicking Saved calls.
Its RSC response and stylesheet both finished with HTTP 200, while the URL and
screen did not change. The local bridge stripped Next.js development request
IDs used to pair the Flight and HMR debug streams. The installed Next 16.3.3
source confirms those header names in client/components/app-router-headers.js
and their use in router-reducer/fetch-server-response.js.

The bridge now forwards those two IDs, segment-prefetch and HMR-refresh headers
only to the local Next server, never to the production API. After the repair,
the actual browser navigated from upload to /calls and /login on port 3017.
A temporary visible heading edit appeared without browser reload and was
removed again, proving the development source is hot-reloaded. No permanent
test marker is part of the patch.

## Checks

- Frontend Vitest: 336/336 passed for the workbench scope.
- Node bridge/service/store/controls: 35/35 passed, including local stub-browser
  geometry checks, route header isolation, frame security and expiry behavior.
- Sales Xray TypeScript and ESLint passed.
- Optimized production build passed. No \_\_review/api or sx-review-local
  transport strings were found in generated production browser chunks.
- Actual Chrome verification used the local bridge and real production GETs;
  no upload, provider request or production mutation was performed.

These checks do not prove the pending account-first auth release, all possible
UI states, report-quality improvements or a production deployment of this patch.
