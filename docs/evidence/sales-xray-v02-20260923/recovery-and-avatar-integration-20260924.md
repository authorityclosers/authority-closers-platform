# Recovery and avatar integration

The processing panel places last-confirmed status, guidance and recovery actions
before the stage illustration and saved file. Awaiting unaccepted approval is
labelled "Ready to analyse"; no provider work or percentage is invented. Existing
action handlers and the action-free static preview remain unchanged. Four focused
panel tests and ESLint passed. The controls have a 44px minimum target height;
actual whole-page viewport visibility still needs rendered verification.

The shared avatar repair is documented in
`../20260924_HOSTED_AVATAR_UPLOAD_TRANSPORT.md`. It was integrated from the isolated
transport worktree without conflicts. Its 68 Python tests and 20 client tests,
targeted lint/type checks passed before integration. Root reviewed the origin,
session and request-scoped adapter changes. An independent Luna source review
found no high/medium blockers. It caught an inaccurate comment claiming the
server disables Uvicorn proxy handling; the comment now accurately states that
this selector uses raw Host and configured origins independently of proxy
handling. Runtime behavior is unchanged.

Root's integration format check caught Prettier differences in the two avatar
client files and the processing panel; applying the pinned formatter corrected
them without semantic changes. Ruff format passes for all six changed Python
source/test files and the Google acquisition fixture. `git diff --check` passes.

A read-only comparison of the owner-selected saved staging call and existing
24-minute production report confirmed identical source hash and byte count. The
existing report has two moments, two suggested actions and thirteen review points.
This supplies a like-for-like baseline; it does not establish new report quality.
Private identifiers and the fingerprint receipt remain outside Git.

No application deployment, recording processing, paid provider request or
production change was performed for this checkpoint. Live auth, avatar and report
acceptance remain required.
