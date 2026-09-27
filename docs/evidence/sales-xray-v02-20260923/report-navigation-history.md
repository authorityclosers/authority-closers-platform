# Report section history behavior

**Date:** 2026-09-23
**Scope:** In-call report section URL navigation; local-only change, no deployment.

## Behavior

Selecting a report section by click or keyboard replaces the current history entry. The call and section remain in the URL for bookmarking and reload, while browser Back returns to the page that opened the report instead of stepping through report sections. Section navigation keeps the shared report panels and audio mounted and does not submit work or reread the report.

The section remains a display selector for the already owner-authorized report. It cannot retarget a different call, select a workflow stage, or initiate report processing.

## Verification

- `report-explorer.test.tsx` and `report-navigation.test.ts`: 9 tests passed. Coverage includes replace-only click and arrow navigation, external history updates without focus theft, preserved panel state, and rejecting a selector bound to another call.
- `node --check scripts/verify-sales-xray-viewport.mjs`: passed.
- Synthetic Playwright fixture harness against `http://127.0.0.1:3116`, with all API routes intercepted before reaching the app service:
  - Mobile 390×844: passed section click, unchanged audio node, no mutation or API read during navigation, bookmark reload, and Back to the seeded workspace URL.
  - Desktop 1440×900: passed the same checks.

The harness did not use a paid/live provider API. No full Next build, server restart, or deployment was run; the local review bridge remained active.
