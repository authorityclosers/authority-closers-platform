# Sales Xray account library and sign-out

Base: `30cd7a8d1aed95e8ead2ee737c9cfa6574d4d599`. Isolated branch:
`codex/sales-xray-account-library-20260914`. This packet completes the enabled
acquisition account journey; the release coordinator owns combined deployment.

## What changed

After signing in and selecting an assigned workspace, a customer can open Saved
calls, choose an earlier upload, replay its original recording and read the saved
report. A fresh browser does not need the previous browser's opaque submission
selector. Guest uploads appear only after the existing explicit account claim.
Sign out is a rendered action, waits for canonical server confirmation, clears
only the opaque submission selector and discards the private document.

The root route now mounts the existing workspace chooser before acquisition.
The disabled acquisition path still mounts the legacy CallStudio. The standalone
Next transport now forwards six exact existing identity endpoints to the configured
internal AC origin: workspaces, context, password login, logout and Google
start/callback. It does not accept browser-supplied upstreams or forward arbitrary
API paths. Google OAuth is routed, but this packet does not claim a live OAuth test.

## Contract and ownership

`GET /v1/conversation/acquisition/submissions` requires an actual AC account and
the configured public Academy. The only optional query is one `before` UUID.
It returns at most 20 rows and a next cursor. Each row contains `submission_id`,
`created_at`, `duration_seconds`, `state` and `has_report`.

The duration is the measured duration rounded up to a second in the immutable
source allowance receipt, displayed as **About**. It is not a new exact acoustic
measurement. Report readiness uses existing validated report/provenance reads.
The query joins immutable account usage or an explicit VisitorClaim to the
source-bound guest submission, recording and permission. Each result is rechecked
through the existing retained-owner port; there is no fake ActorContext or recording
reassignment. Processing expiry cannot renew a lease and does not hide a still
retained call. Deleted, revoked or retention-expired recordings are excluded.
Cursor selection remains owner-bound but survives deletion of the previous page's
last call. Unknown and duplicate query parameters cannot supply an owner.

Successful library and owner-error responses are private/no-store. Malformed UUID
queries use the existing generic framework validation response and disclose no call
data. Library reads create no jobs, grants, claims or
provider requests. Opening a row explicitly selects that submission and reuses
the existing report/progress/playback APIs and valid checkpoints. Unclaimed guest
uploads are never silently claimed when entering the library.

## Test receipts

Portable logs and XML are in `account-library-20260914/`; their hash index records
the exact files and source hashes. Portable logs normalize line endings and trailing whitespace; original logs remain in the external audit directory. Synthetic browser data stays outside Git except
for the bounded screenshots/network receipt in this packet.

- Full standalone unit suite: **122 passed, 17 files**, 15.95 seconds. Includes
  strict library decoding, pagination/duplicate handling, explicit row selection,
  logout pending/failure/success and existing report/identity regressions.
- Actual disposable PostgreSQL plus cookie HTTP: **8 passed**, 128.09 seconds
  (two new library cases plus six existing submission cases). Includes guest and
  direct-account uploads, explicit claim, foreign person/tenant/cursor denials,
  no recording reassignment or job creation, 20+3 stable pages, deleted cursor,
  natural processing lease expiry and immediate deletion/revocation visibility.
- Optimized Next standalone build passed, including `/calls`; TypeScript passed
  during the production build. Scoped Python Ruff and mypy passed.
- Compiled Next -> actual TCP AC API -> disposable PostgreSQL browser journey:
  **1 passed**, 47.46 seconds on the final reviewed build;
  guest upload/consent, C1, provider-plan consent, C6 report, reload, native media
  playback, actual password login, two-workspace selection, explicit claim, a fresh
  browser without a selector, Saved calls, keyboard report opening, sign-out button
  returning 204 and subsequent private library/report/source requests returning
  HTTP 401. The guest deletion journey remains covered. The 320px library reflows
  without horizontal overflow; desktop and mobile screenshots were visually
  checked. Final runtime receipt records the build ID and individual HTTP statuses.

The browser uses zero intercepted AC API responses. Cloudflare's widget and
verification, the native socket adapter and three provider responses are explicit
synthetic test boundaries. AudioAtlas runs locally on synthetic audio. There are
**zero external provider calls and zero new spend**. These checks prove account
and report transport, not provider coaching quality or public capacity.

The first database attempt lacked the new worktree's verified native binary;
source/binary-hash-checked reuse corrected setup. Subsequent tests caught missing
verified email and an attempted immutable-lease edit in the synthetic fixtures;
the final fixture advances its clock naturally instead. No guard or database
trigger was weakened. An initial passing browser capture showed library loading;
the final proof waits for the actual row before capturing the screen.

Independent Luna review found no backend or fixed identity-transport regression.
It found one UI pagination issue: an empty page after concurrent erasure hid the
next cursor. The empty state now requires both no rows and no cursor, and a
behavioral test loads the subsequent retained call. The reviewer verified that
correction and reported no remaining defect for it. The final UI/build/browser
receipts include that correction.

## Release and report boundaries

Dipak's ten-page reference PDF SHA-256 remains
`4fad19ce3234848c9f992190f9f498184bb8be6996664a9e7cb6dc133aa3a0eb`.
Its 14-point overview is already integrated in this base; see
`../contracts/SALES_XRAY_DETAILED_OVERVIEW_V1.md`. This change makes saved reports
discoverable without replacing that overview or regenerating coaching output.
The private real-call preview is a saved draft, not a new provider benchmark or
Dipak/Suyash adjudication. Numeric publication remains held at 95 actual versus
100 declared source weights.

This leaf is implemented and tested locally. Combined CI, immutable image,
authenticated staging and production publication of this exact leaf remain the
release coordinator's work and require separate receipts.
