# Existing-call deep-link entry

**Date:** 2026-09-23
**Scope:** Sales Xray standalone and learner routes; local-only change, no deployment.

## Behavior

Opening `/?call=<submission-id>` or `/sales-xray?call=<submission-id>` now starts with a neutral “Opening your saved call” state. The route accepts only one well-formed UUID selector. That selector is a lookup hint; the page displays no call data until the same-origin submission read confirms the requested ID and the existing report/transcript contract validates the report.

While workspace access is checked, the standalone and learner shells use saved-call-specific loading copy. Static-preview builds do not read request `searchParams`; the client holds a neutral surface until it resolves the query after hydration. An unavailable call gets an explicit retry, sign-in, or deletion-only path as appropriate. A readable call with no report moves to the existing processing view. A report-ready call stays on the opening surface until its owner-authorized transcript and report reads finish, then renders the report directly.

Restore remains read-only: no quote, acceptance, upload, claim, or processing request is sent for a restored call. Changing the selected call clears the previous call and report before beginning the next owner read. Changes to other query parameters, such as a report section, do not retrigger the restore.

## Verification

- Sales Xray page, studio, and workspace-gate tests: 77 passed. Coverage includes delayed owner reads, direct report opening, saved-call failure recovery, static-query routing, and switching call IDs without exposing the previous report.
- Learner route and acquisition-journey tests: 11 passed. Coverage includes delayed owner reads, pending processing state, and report recovery when upload-policy/session setup reads are unavailable.
- Focused ESLint checks passed for the changed Sales Xray and learner route files.
- Final TypeScript checks passed for both apps.

The static-preview route was covered by a page-level test that rejects any attempt to await request `searchParams`. A full Next static-export build was not run because the local 3016/3116 review bridge was active and shares the app build output.
