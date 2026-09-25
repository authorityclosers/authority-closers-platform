# Live Calls and recent home activity

The authenticated standalone home now shows up to three real saved calls only
when data exists. The preview is absent during upload, processing, report and
deletion views, and does not add a second main landmark or an empty table.

Calls refreshes from the owner's existing read endpoint after a saved upload,
on focus, and every 15 seconds while a visible first-page call is processing.
Reads have a 12-second timeout. Manual refresh replaces the first page so removed
calls disappear; unchanged page membership preserves already loaded older calls.
An account/session/tenant change remounts the private list. Late or queued reads
cannot publish after identity change or unmount. Refresh does not start analysis.

Validation on the release branch:

- CallsLibrary: 20 focused tests passed, including timeout recovery, pagination,
  queued refresh, real preview rows, account changes and unmount.
- Acquisition studio: 83 focused tests passed, including hidden empty home,
  saved-report navigation, duration and read-only preview behavior.
- Targeted TypeScript, ESLint, formatting and diff checks passed. A transient
  Vite/happy-dom file-read failure occurred before collection; the retry passed.
- Independent source review found no blocker. Its queued-unmount read nit was
  addressed with an unmount/generation guard and regression coverage.

These are local tests and source review. They do not establish a deployed release,
real provider success or report quality. Brain 3 coverage remains a separate
source-to-behavior requirement; populated report sections are not proof of it.
