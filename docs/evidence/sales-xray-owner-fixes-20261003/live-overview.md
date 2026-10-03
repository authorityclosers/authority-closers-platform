# AUT-992 E0.1: remove the Live Overview pill

This is the first small PR in the owner's ordered v0.16 fix list. The next slice
is the Transcript icon, after this PR merges and the sales-xray lane is released.
AUT-992 remains open until every slice is merged and checked on dev and staging.

Source base: `7d65c62906f314acaf6ea1bcba077e743c6894d8`.

The dashboard header no longer renders the Live Overview pill. Its unused badge,
dot and pulse animation styles are removed. The existing dashboard title and
navigation stay in place.

## Verification

- Sales Xray lint and typecheck: passed.
- Prettier checks for both shell files: passed.
- Full web test run: 1,153 passed, 6 skipped, 3 failed. Two upload-navigation tests
  exceeded the 5-second deadline; the third failed after those timeouts.
- Isolated rerun of all three failures, with one worker: all 3 passed.
- Latest-main lane gate: `ok: task/sales-xray/992-owner-fixes may be worked on`.
- Browser checks at 390×844 and 1440×900: passed. The pill is absent, the Dashboard
  title remains in the header, navigation and the main landmark remain, and
  horizontal overflow is zero. The guest sign-in action remains visible.

The branch ran in a temporary, loopback-only Next development server. The browser
mocked the development review health bridge and unauthenticated API reads; other
hosts and all writes were blocked. This checks the guest shell, not an authenticated
account or a deployed release. The temporary server stopped after capture.

- [Phone screenshot](live-pill-after-390.png)
- [Laptop screenshot](live-pill-after-1440.png)
- [Browser receipt](live-pill-receipt.json)

## Deployment check

Open <https://salesxray-dev.authorityclosers.com/dashboard> at 390 px and laptop
width. Verify the Live Overview pill is absent, the Dashboard title and navigation
remain, and the page has no horizontal overflow. Repeat on staging after its
normal deployment.

The public dev URL requires Cloudflare Access sign-in in this run. Its existing
loopback app was inspected before editing. That app serves the UI checkout, so
this sales-xray branch needs separate local browser evidence before merge.
Public dev and staging verification remain outstanding; no deployment was run.
