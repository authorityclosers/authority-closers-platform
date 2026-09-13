# Sales Xray saved report browser correction

Opening a saved call with a completed AudioAtlas run and an imported report
attempted to prepare a new processing plan. That prevented the existing report
from opening when only local measurements were enabled. `CallStudio` now opens
an available saved report before considering another plan. This applies to both
the 48 kHz local and 16 kHz hosted recipes; report/source/transcript validation
remains in place.

The regression exercises both exact acoustic recipes, verifies the saved report
and transcript requests, and asserts that no plan quote is posted. The actual
browser fixture now isolates each flow's database schema/control account and
uses the current private-upload consent labels.

## Executed validation

Receipts are retained outside Git at
`D:/Projects/authority-closers-release-transfer/2026-09-13-sales-xray/receipts`:

| Check | Result | Receipt |
| --- | --- | --- |
| CallStudio unit tests | 19 passed | `call-studio-saved-report-02.xml` |
| TypeScript | Passed | `call-studio-typecheck-02.log` |
| Actual Next static preview build | Passed | `0032-callstudio-fixed-build.log` |
| Chromium over TCP, AC cookie auth, PostgreSQL, native WAV worker | 2 passed in 78.11 seconds | `0032-callstudio-browser-fixed-01.xml` |
| Imported report browser/network assertions | Passed | `0032-callstudio-browser-fixed-01/authenticated-browser.json` |
| Durable C2/C4/C5/C6 report browser/network assertions | Passed | `0032-callstudio-browser-fixed-01/durable-authenticated-browser.json` |

Both browser flows verify unauthenticated onboarding, saved report/transcript
binding, authorized WAV playback and timestamp seek, private no-store 206 byte
ranges, 390 px layout, reload without repeat analysis, explicit upload consent,
new private upload through the local native worker, and stopped report polling
after local completion. Browser error and external-request collections are empty.
Screenshots accompany both network receipts.

The earlier failing receipts `0032-callstudio-browser-final.xml` and its evidence
directory are preserved. The successful run used the rebuilt frontend and fresh
synthetic data in disposable PostgreSQL schemas. API routes were not mocked;
the durable provider broker was synthetic. This proves local behavior, not new
provider inference, Google login, Linux confinement, staging or production.

Commands used: `vitest run`, `tsc --noEmit`, `next build` with
`AC_SALES_XRAY_STATIC_PREVIEW=1`, and
`pytest tests/e2e/test_sales_xray_report_browser.py -q --tb=short` through the
external local-proof runner. Prettier for both changed UI files, Ruff for the
browser fixture and `git diff --check` also passed.
