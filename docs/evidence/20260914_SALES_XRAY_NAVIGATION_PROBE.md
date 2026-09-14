# Standalone Saved calls navigation probe — 14 September 2026

CI run [34798730242](https://github.com/authorityclosers/authority-closers-platform/actions/runs/34798730242)
on `ae289965110bbf1dcf39191b23929eed507cdb87` finished with one failed Python
test, 5,409 passed and 1,001 skipped. Its sole failure was the standalone browser
proof rejecting `HEAD /calls/: net::ERR_ABORTED` after all sign-in, workspace,
report, playback and sign-out assertions had passed.

The account navigation now contains a Next `Link` to `/calls`. The installed
Next 16.3.3 `client/components/segment-cache/cache.js` uses HEAD requests for
static-export Link prefetch redirect checks. A document replacement can cancel
that speculative request. The proof already accepts the corresponding exact
`HEAD /` and `HEAD /login/` events and retains them in its receipt.

This test-only correction adds the exact `HEAD /calls/` aborted event to that
same set. It does not allow GET page failures, other HEAD paths or newly allow
any API failure. Existing API cancellation exceptions still require their exact
observed status and independently verified session effects. External requests,
browser errors and every other failed request remain fatal. The complete failure
list is retained separately from accepted navigation cancellations.

## Validation

- Fresh static export from the isolated worktree passed compilation, TypeScript
  and page generation, including `/calls`. Build ID: `T48arsFf8FLSNIRhUwNkF`.
  An earlier attempt to reuse a local export was rejected because it lacked
  `/calls`; it was not used for the passing proof.
- Real Chromium → loopback HTTP API → dedicated disposable PostgreSQL browser
  proof: **1 passed in 33.06 seconds**. The new build was used. No AC API response
  was intercepted and no provider or Google request was configured.
- The native fixture binary was reused only after checking its digest and
  comparing the native source with the release worktree.
- Ruff lint, Ruff formatting and `git diff --check` passed.
- Independent Luna xhigh review found no actionable issue with the correction
  or the preserved negative checks.

Portable receipts are in `navigation-probe-20260914/`; logs normalize LF endings
and trailing whitespace. Originals remain in the external release audit directory.
The passing local run also observed the exact cancelled `HEAD /calls/` request;
it remains visible in both the complete failure list and accepted-cancellation
list, with zero unexpected failures. This is a passing focused proof, not a claim
that the combined CI rerun or a deployment has passed.

No production code, API, authorization, provider policy or release gate changed.
The release owner must integrate the exact leaf and run the combined candidate.
