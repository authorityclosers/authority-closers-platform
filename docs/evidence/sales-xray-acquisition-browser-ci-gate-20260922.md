# Sales Xray acquisition browser CI gate

This evidence records the required CI path for the compiled Sales Xray guest
acquisition journey. The gate runs in its own GitHub Actions job with a fresh
loopback PostgreSQL service, Node 24.19.0, the locked Playwright Chromium
runtime, a verified AudioAtlas native build, and a production `next build`
using the loopback API origin. The static preview build remains a separate
frontend pre-validation check.

The wrapper at
`scripts/ci/verify_sales_xray_acquisition_browser.py` invokes exactly
`tests/e2e/test_sales_xray_acquisition_browser.py::test_compiled_guest_upload_report_reload_claim_and_deletion`.
It refuses a missing test, a skipped JUnit case, a stale or missing receipt, a
non-production build, provider/API interception, page errors, or missing
journey assertions. It writes a bounded sanitized receipt containing build
identity, HTTP status counts, synthetic-adapter declarations, and the required
journey assertions. No raw audio, credentials, provider response, submission
identifier, or unredacted network path is uploaded by the artifact step.

The browser test uses only its explicit synthetic challenge, native-media, and
provider broker adapters. The API, cookie sessions, PostgreSQL state, offline
worker, report, account claim, private playback, reload, logout, access denial,
and deletion request remain local components under test.

Validation performed for this change:

- The focused CI contract tests parse the workflow and enforce the dedicated
  job, isolated database URL, native prerequisite, non-static build, explicit
  wrapper invocation, artifact upload, and aggregate validation dependency.
- Local production build and native AudioAtlas build passed.
- The full wrapper passed against disposable PostgreSQL on 2026-09-22 with
  Node `v24.19.0`: one required JUnit case, 15 journey assertions, 76 local
  HTTP receipts, zero API interceptions, zero provider network calls, and no
  page errors. The sanitized receipt was emitted at
  `D:\ac-xray-reliable-browser-evidence-a77e90da-11e1-476c-b6d1-a2db71f01f29\sales-xray-acquisition-browser-receipt.json`.

Independent read-only review of the concurrent report and retained-C5 changes
found no P1 or P2 defect. The scalar-finding adapter joins detailed evidence by
declared finding index, rejects duplicate/out-of-range identities, remaps
dependent overview references after drops, and keeps unbound prose in bounded
provider extras. Flattened overview envelopes still go through the strict
versioned model, with required-field omissions failing closed and the optional
root `business_impact` shape preserved. Retained-C5 fingerprints include the
validator revision while the original command key still replays its historical
receipt; the run lock serializes same-revision version allocation and the
recovery PG concurrency test passed. Targeted overview tests passed (`69`), and
the parent reported the retained-C5 PostgreSQL upgrade/replay/concurrency tests
passing with the baseline recovery suite.
