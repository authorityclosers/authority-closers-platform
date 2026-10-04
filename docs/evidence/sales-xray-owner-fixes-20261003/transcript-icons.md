# AUT-992 E0.2: Transcript icons

Source base: `22bbede4806499ef4487268e6ff2273b546e7ca8`.

The Transcript action, its More menu entry and the Transcript tab now use the
existing Lucide FileText document icon. This is the second small PR in the
owner's ordered fix list. The next slice is the saved-on-device message after
this PR merges and releases the sales-xray lane.

## Verification

- Sales Xray lint and typecheck: passed.
- Prettier checks for both changed components: passed.
- Existing report header, report modes and full-shell fixture tests: 52 passed.
- Latest-main lane gate: `ok: task/sales-xray/992-transcript-icon may be worked on`.
- Browser checks at 390×844 and 1440×900: document icons render in all three
  Transcript controls; header and menu actions open the reader; the reader
  closes; the Transcript tab selects; horizontal overflow is zero.

The browser used this branch's existing fictional report fixture on a temporary
loopback-only Next development server. API reads received mocked unauthenticated
responses; all writes and external hosts were blocked. No account, recording or
provider was used. The temporary server stopped after capture.

- [Phone screenshot](transcript-icons-after-390.png)
- [Laptop screenshot](transcript-icons-after-1440.png)
- [Browser receipt](transcript-icons-receipt.json)

## Check on dev

Open <https://salesxray-dev.authorityclosers.com/review-fixture/shell> at 390 px
and laptop width. Check the document icon on Transcript, open and close the
reader, then repeat through More. Select Tabbed view and check the Transcript
tab's icon and selection. The fixture contains fictional data.

The dev loopback fixture was inspected before editing. Public dev requires
Cloudflare Access sign-in in this session. Post-merge verification of this slice
on dev and staging remains outstanding.

PR #267, the first Live Overview pill slice, is merged. A 390 px check on the dev
loopback dashboard after merge found zero Live Overview pills and one main
landmark. Its staging verification is still outstanding. AUT-992 stays open
until all slices are merged and checked on dev and staging.
