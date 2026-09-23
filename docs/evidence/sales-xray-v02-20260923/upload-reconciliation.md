# Same-session upload retry reconciliation

Local change; not a production deployment claim.

The pinned-source cloud audit identified that a failed PUT response could lead
the same mounted browser to issue another PUT without checking the saved source.
Local inspection confirmed the behavior. A retry now reads the same submission
first, verifies its ID and SHA and restores verified progress. Its allowance is
read from the session authority. It does not estimate or deduct usage locally.

Only a 404 lookup permits another PUT. Denial, unavailable lookup, malformed
payload and mismatched source identity remain errors without another upload.
Existing server ownership, idempotency and admission checks still apply. Reload
already had a separate saved-submission recovery path and retains it.

The acquisition studio suite passes all 55 tests. The new regression models a
committed upload whose response is lost, advances the browser clock by 31 minutes
and verifies GET-before-retry with exactly one PUT and no new plan/acceptance
request when automatic progression is already confirmed. Other regressions cover
no saved submission, source mismatch, access denial, malformed progress and an
unavailable lookup. TypeScript and changed-file ESLint passed.

This is mocked browser-contract evidence, not a real 31-minute provider run or a
new production billing proof. Real staging/reload/guest/account verification is
still required for the integrated release.
