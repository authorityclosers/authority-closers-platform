# Combined UI integration and release handoff

## Superseding acceptance: release held

The user now explicitly requires reviewer-only login and workspace access,
separate from student/learner access, with no reviewer UI in learner flows.
Admin must retain review details and invitation management. The shared Academy
flow documented below does not meet that requirement. These results preserve a
tested integration checkpoint; they are not final acceptance or a deployment
instruction. PR 58 is a draft until the separation is implemented and verified.

This merge combines the root's frozen UI branch `5459c98` with the original UI
owner's `e219ac5` packet. It preserves the revised Coach authoring flow, Admin
control center and calendar-based invitation controls, adjacent review audio and
feedback, collapsed references, clip selection and search, and one Sales Xray
navigation entry.

The original packet contributes the password-reset completion links, normal
Google registration guidance, strict invitation receipt checks and the verified
scoped ShellCheck directive. The root's verification-help continuation note and
its assertions are retained alongside both reset and successful-verification
regression tests. No canonical backend or database source differs from `5459c98`.

The shared review package now declares `test: vitest run`, so its seven existing
behavior tests execute under the normal workspace test command and CI.

Luna's independent review found that a malformed email could throw synchronously
before Promise handlers attached and leave the invitation panel busy indefinitely.
The merged panel now awaits the API inside try/catch/finally, always clears the
busy guard, and displays a human-readable schema-validation error. A mounted
regression test uses the actual email schema, corrects the address, and confirms
the next attempt runs. All three invitation panel tests pass.

## Combined validation

- Admin: all 756 tests passed across 40 files.
- Shared reviewer form: all 7 tests passed.
- Learner: 1,774 tests passed; one unchanged development trace privacy test exceeded
  its five-second limit during concurrent builds. All four tests in that exact
  file then passed unchanged in an isolated 399ms run. The preceding full learner
  run on the recovery packet passed all 1,775 tests. No timeout or assertion was
  relaxed, and the initial failure remains visible in the session evidence.
- Learner, Admin and Coach production builds all passed, including TypeScript.
- All three app ESLint checks passed. Whole frontend Prettier, browser-script Ruff,
  installer ShellCheck 0.11.0 and diff checks passed.

## Fresh browser evidence

The merged source was rebuilt before the browser checks. The learner screenshot
shows one Sales Xray navigation entry; it supersedes the earlier duplicate-entry
capture as layout evidence. Exact normalized source hashes are in
`combined-ui-browser-20260913/` receipts.

Learner: `combined-ui-browser-learner-01` passed in 33.04 seconds against actual
HTTP, private storage and disposable PostgreSQL. Invitation acceptance 201,
private audio 206, feedback save 201, idempotent replay, one durable submission
after reload, dirty-navigation protection, 390/320px layouts and dark rendering
passed. No invitation token was persisted in browser storage.

Admin: `combined-ui-browser-admin-01` passed in 85.41 seconds. Real invitation
queue/revoke requests returned 201/200; assignment create/revoke/reload, request
receipts, local calendar inputs and 390/320px layouts passed. Its API receipt is
included beside the learner proof.

Authentication resolution and shell profile reads are synthetic fixtures. The
learner uses its production Next build and Admin uses explicit local preview.
No real invitation mail, provider call, production state change or live release
acceptance is claimed by these local checks.

## Final release ownership

The root release coordinator has integrated the revised UI, video encoder cost
and selected-environment OAuth fixes into its consolidated branch and owns the
single final image dispatch and deployment. This PR supplies the combined UI and
recovery corrections for that candidate; it does not launch another installer.
Live deployment, invitation delivery, hosted runtime acceptance and the broader
remaining scope in `20260913_V02_UI_AND_CALIBRATION_SCOPE.md` must be reported
separately from this implementation evidence.
