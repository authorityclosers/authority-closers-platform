# Coach, Admin and reviewer experience integration

This work integrates the reviewed assignment implementation (`fa1dcbc`), invitation
backend (`7ffd092`, `14781f6`), Coach authoring (`2d1c36c`), Admin control center
(`0055fbc`, `8910bc8`), navigation/routing (`6301fa4`) and observed provider-catalog
contract fix (`665b0d0`) above the validated `99cdee5` candidate. Invitation auth,
response validation and recovery incorporate the corresponding files from `94403f3`.
Root improved the mounted reviewer and invitation layouts without replacing the
primary assignment adapter or its canonical source checks.

## Behavior

Audio and feedback are adjacent on desktop. Findings are grouped separately from
reference frameworks; displayed counts reflect actual observations only. Small
screens stack the workspace. Review lenses have practical guidance, and clip
search does not change the selected evidence or erase feedback. Technical IDs and
reference materials remain available under disclosure controls.

Admin primarily invites reviewers by email. Existing-account assignment by ID is
available under Advanced. Calendar inputs convert local time to canonical epoch
seconds and reject malformed dates. Invitation drafts survive queue hydration.
Failed unchanged sends reuse their request identity; edits and new sends after a
confirmed success use new identities. Revocation has explicit confirmation feedback.

Invitations stay in same-origin fragments or component memory. Registration,
verification help and recovery preserve return links without including the bearer
in auth requests. The verification help page explicitly keeps the invitation tab
available while email verification occurs in another tab. Acceptance supports
transient-error retry and React effect replay without duplicating the request.

## Independent review and corrections

Luna static review identified signup continuation, missing acceptance retry,
sticky successful invitation request identity, queue-hydration draft loss and
incomplete dirty-state tracking. These are corrected in this integration. Focused
tests cover the request identities, calendar conversion, draft preservation,
auth continuation, accepted source binding and review-setting navigation guards.

## Verification

- Admin Sales Xray suite: 38 tests passed, including the live catalog contract fixture.
- Learner review, invitation/auth continuation and Sales Xray navigation: 27 tests passed.
- Shared reviewer form: 7 tests passed.
- Combined Learner, Admin and Coach production builds pass on Node24.19.0;
  Admin/Learner typecheck and lint pass. Changed frontend formatting, Python proof
  formatting/lint and `git diff --check` pass.
- Coach authoring agent: 60 Studio tests passed; Admin lint/typecheck/build passed for its isolated commit.
- Actual local HTTP/PostgreSQL browser: invitation acceptance201, source range206,
  feedback save201, idempotent replay to the same record, history after reload,
  dirty sidebar/keyboard navigation protection, no page errors, no horizontal
  overflow at320/390 pixels, light/dark layouts. Authentication resolution is a
  synthetic actor fixture; the review routes/services/storage/database are real.
- Actual Admin HTTP/PostgreSQL browser: invitation create201 and revoke200 after
  reload; assignment create201, revoke200 and reloaded revoked state;320/390-pixel
  layouts pass. No real email or provider request was sent.
- Coach browser: actual Coach app with synthetic GET fixtures, course outline
  selection, lesson editing, unsaved draft hint, preview/publication guidance and
  desktop/mobile layout pass. No mutation was made. The synthetic upload availability
  response intentionally does not prove provider availability. Admin-to-Coach handoff
  is not proven by that fixture because its local Coach origin was not configured.

Receipts and screenshots: [browser evidence](v02-review-experience-20260913/).
Full external test receipts retain each failed attempt and superseding result under
`D:/AC-authority-closers-release-audit/`. Initial browser attempt01 lacked the local
native binary;02 reached the page but used an obsolete button label;03 passed.
The final invitation-mode browser proofs also pass. Native binary and source were
verified against their manifest before the real local analysis fixture ran.
The receipts' `backend_commit` working-copy marker is descriptive rather than a
Git object ID; the canonical Python source is unchanged from `77b918c`. Frontend
file hashes in the receipts identify the exact UI under test.

## Release boundary

These are local implementation proofs. Production/staging deployment, real mail
delivery and complete hosted Sales Xray acceptance are separate required release
checks. The Admin benchmark page is preparation/status, not a run launcher or model
training interface. See [remaining UI/calibration scope](20260913_V02_UI_AND_CALIBRATION_SCOPE.md).
No paid call, credential purchase, production database edit, numeric AI score or
new public media publication occurred in this UI integration.

## Superseding Coach browser receipt and final independent review

The clean Coach browser pass 03 corrects the synthetic upload-availability fixture
used in pass 02. Its receipt and desktop/mobile captures are preserved in
`v02-review-experience-20260913/coach-clean-03/`. It verifies the actual Coach page,
outline selection, editable lesson title, draft guidance, preview/publication
information and responsive layout. No non-GET request occurred. Its small upload
limit is fixture data, not the deployed media policy. Earlier receipts are retained.

The independent Luna reviewer rechecked integrated UI tip `5459c98`: all five
reported invitation/auth/draft findings are resolved, with no new P1/P2 finding.
This was a static re-review, not another full test run. Merge `a73bef5` preserves
exactly the tested application, package, script, database and test code from that
tip while retaining the later Sales runtime evidence. Patches `7b161b1` and
`f3e7316` separately add the already tested video encode preset and environment
correct OAuth probe; their focused evidence documents remain attached.
