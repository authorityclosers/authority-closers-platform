# Sales Xray provider readiness

## Problem and behavior

Selecting the approved Deepgram preset still produced the ElevenLabs C2 recipe.
The guest plan quote was therefore rejected before transcription could start.
The transcription planner and manifest now bind the recipe to the exact supported
provider/model pair. Existing ElevenLabs plans remain valid; mixed pairs fail.

Admin now lists server-approved provider presets with a direct switch action.
The active state requires both the saved revision and configuration digest.
Switching, saving and importing share a mutation lock; stale responses offer a
reload, and activation success is checked against the requested preset identity.
Provider credentials, approved routes, budgets and accepted plans are unchanged.

## Implementation evidence

- Route fix: `11be375ab17e819c3da212a480e02465b8a32d5a`.
- Provider preset controls: `0eacc809bd327d7e6d477158f42604af7e177ee0`.
- Preset identity and mutation safeguards: `492a4b2`.
- Route/manifest tests: 35 passed in the integration worktree; independent review
  ran 62 affected inference, activation and broker tests successfully.
- Admin controls: 23 focused tests passed; typecheck, lint and formatting passed.
  The local review used Node 22 with an engine warning; release CI uses Node 24.
- Full unrelated Windows suites encountered existing temporary-directory guards
  and child-process setup failures. Release CI remains required before deployment.

## Release verification

Use the verified immutable application bundle and canonical installer. Reuse the
unchanged, verified native helper. Preserve the selected Admin provider revision.
After deployment, request a fresh plan for the saved guest recording, then prove
transcription, coaching output, playable source evidence and Admin visibility.
Passing unit checks alone does not establish a successful production analysis.

The separate report and Admin design task is not included in this core release.
Document export changes are paused at the user's request.
