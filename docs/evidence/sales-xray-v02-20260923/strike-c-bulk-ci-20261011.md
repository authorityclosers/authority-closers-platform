# Bulk import continuation: cancellation fixture

PR #437's preview-head application run 38094362078 failed only
`test_cancel_after_final_authority_can_commit_private_bytes_but_drains_before_return`.
Its two-second thread-readiness wait elapsed before final byte publication; the
cleanup then expected cancellation from a request it had never cancelled.

The fixture now allows ten seconds for the explicit readiness event, keeps the
writer held for up to twenty seconds, and cancels/drains an outstanding request
even when readiness fails. Successful readiness still proves cancellation cannot
return while private byte publication holds its slot, and replay publishes the
same hash. It avoids a second cancellation of an already cancelling task. No
studio-video runtime code changes.

On the integrated `f88161f` tree, 52 focused bulk/native/authority/backup checks
passed (110.10s), including the original failing test. After the fixture change,
all 41 studio-video byte tests passed (49.98s). This is loopback/disposable and
fictional-data proof; final-head CI remains required. No hosted write or provider
dispatch occurred.

## Bulk component production-build proof

The current `BulkRecordingImport`/preview components and page kit were imported
directly into a temporary Next 16.3.6 harness outside Git. `next build --webpack`
and `next start` ran under `ac-heavy`; the browser and server were closed in a
`finally` block. A populated fictional batch covers queued, working, retrying,
failed with Try again, done, unassigned and source-hash reuse. Unassigned has no
processing stage. This is component proof, not an authenticated deployed journey.

The preview heading now stays compact on phones. Its scoped CSS uses the shared
UI font, including Devanagari, and explicit 32px/44px control floors without new
colours or changes to A's pages, shell, tokens or shared kit. All 36 focused bulk
frontend cases, frontend typecheck and changed ESLint pass. The four reviewed
production screenshots have no sideways overflow or page errors; visible file
inputs/buttons measure exactly 32px desktop and 44px phone. Files:
`/home/acdev/strikes/1676/shots/2026-10-11/bulk-import-{1440,390}-{light,dark}.png`.
The reproducible harness and receipt are in the strike's `bulk-browser/` folder.

CI run 38099761207 built and tested the frontend successfully, then its final
Prettier step rejected the preview's multiline Panel opening. The repository
formatter collapses that opening to one line. This changes only whitespace;
the existing 36 cases and production screenshots exercise identical JSX.
CI's Python gates and acquisition browser also passed at 8f0f42a. The unrelated
shared-migration slot with #442 remains recorded separately.
