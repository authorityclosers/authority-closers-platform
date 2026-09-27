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
# Final report integration and recovery placement

Integrated the UI studio report handoff `e57c1084749dc25e1494f4b6ca989eb6397d1983`
as `4fc17e25`, preserving the root's deduplicated moment groups and related
observations alongside inline playback actions. Continuous reading and tabs use
the same report content and audio controller. Moved the existing error/recovery
block above the content grid without changing retry or paid-plan handlers.

The combined acquisition, report modes, moments and skills suite passed 99 tests
with one worker. The lost-quote test additionally asserts that recovery precedes
the call panel and retains the separate read-only status/review/accept actions.
These checks do not establish hosted layout, login delivery, or report quality;
those require exact-release staging and production evidence.

Final lint identified synchronous effect state updates in the new report modes
and skills components. The reading bookmark now synchronizes with the scheduled
DOM scroll; switching modes resets the selected skill before committing its
render. Thirteen focused follow-up tests pass, including a stale-dialog
regression, and final focused ESLint passes. The whole frontend formatting
check and Sales Xray TypeScript check passed. A transient local module-resolution
failure during lint was not counted as a pass; the successful rerun used the
same installed ESLint and source files.

Exact-source CI for `b10e8cc7` found the same effect reset issue in the remaining
Next-call plan component outside the initial focused lint set. It is corrected
with a conditional mode-change reset. Five Next-call plan tests, including the
mode-switch dialog regression, and full Sales Xray ESLint now pass. That CI run
also has a separate acquisition browser failure under investigation; `b10e8cc7`
is not deployable and its successful native build does not override those gates.

Independent review found that clicking the already-selected Tabbed view control
could reset a directly bookmarked section. Both active mode buttons now preserve
the current view rather than navigating again; all eight report-mode tests pass.
The reviewer found no additional high/medium recovery-placement issue. The CI
Python shard's single failure was a 15-second PowerShell syntax-check timeout;
the unchanged test passed locally in 0.95 seconds and remains required in CI.

The compiled acquisition browser journey now passes with an explicit switch
from the default Reading view to Tabbed view before inspecting Moments. CI also
passed all 451 Sales Xray frontend tests. Its remaining learner integration
failure had the same obsolete tab assumption; the learner journey now checks
the default Reading view before switching. All ten focused learner acquisition
tests pass. One local run failed to open a temporary transform file and was not
counted as a pass; the unchanged rerun completed successfully. Hosted acceptance
and report-quality comparison remain outstanding.
