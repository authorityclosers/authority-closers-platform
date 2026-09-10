# Local learner refinement — 2026-09-08

Implementation worktree: `codex/local-staging-dev-bridge`. This is local working-tree
evidence, not a staging/production release or a claim that v0.2 is complete.

## Changes and checks

- Player: contained 16:9 picture, compact in-frame controls/settings, native caption
  clearance above controls, Escape/focus handling, and hidden redundant READY row.
  102 focused player tests passed; learner TypeScript and scoped lint passed.
  At that checkpoint, stage click/double-click gestures were not implemented.
  The subsequent immediate picture-control change is recorded below. No playback
  authorization/evidence rule was changed.
- Updated `scripts/verify-local-adaptive-video.mjs` to exercise speed, captions and
  skip controls through their actual Settings UI. Root's clean native Chrome run
  passed 23 checks: 360p/1080p/2160p/Auto, actual 3840×2160 decoding, rate, mute,
  seeking, fullscreen, and contained controls at 320/390/1440px. Original paused
  presentation settings were restored. Canonical activity state/revision/actions
  were unchanged; no observed main-document mutation or external request attempt.
- Progress: one course summary, plain-language copy, expandable module details,
  and optional activity insights fetched only on expansion. Missing/partial totals
  remain unavailable; identity, membership, session recovery and offline disabling
  are preserved. Removed the route's duplicate totals and unavailable motivation
  cards without inventing achievements. 19 focused tests passed, including mounted
  expansion, lazy read/cancellation, retry and expired-session checks. Independent
  review found no Critical/Important issue; full learner TypeScript/scoped lint passed.
- Practice sound: optional volume and explicit Tap/Saved/Celebrate previews;
  reward > confirmation > selection priority prevents clicks cutting off rewards.
  Four-second preparation limits cover fetch, body reads, resume and decode;
  stop/mute/dispose cancel previews, and stale results cannot play later.
  42 sound/control/engine tests passed. Independent review identified the original
  stalled-audio bug; its fix and five added regressions were reviewed by root.
  Existing same-origin CC0 samples are unchanged. This is not a subjective listening
  approval or a replacement sound-design claim. No reward/progress API was added.

## Browser records

- Accepted native playback: [root proof](screenshots/native-adaptive-video-2026-09-08T12-05-01-741Z/proof.json).
- Accepted overlay/caption layout: [player proof](screenshots/player-overlay-20260908-final/proof.json).
- Earlier root run `native-adaptive-video-2026-09-08T12-02-48-186Z` failed while
  saving its final desktop screenshot, before the final audit. Preserved as failed
  evidence, not counted as a pass. Its clean rerun is linked above.
- Shared Admin/Coach styling has [separate evidence](20260908_OPERATIONS_SHARED_THEME.md).
- Subsequent delegated read-only Progress QA: [proof](screenshots/progress-clarity-20260908/proof.json).
  Default full-page height fell from 4051 to 2490px at 390px and from 2910 to
  1911px at 1440px, with no measured horizontal overflow. Native Enter/Space
  and click expansion worked. Scope switching fetched no insights; explicit
  expansion produced two development-runtime requests, not a single-request claim.
- Subsequent [sound-control QA](screenshots/practice-sound-clarity-20260908/proof.json)
  verified the actual switch and explicit preview at 390px; local preferences
  were restored. It is not a subjective audio-quality approval. The older
  `local-practice-effects-proof.mjs` targets stale labels and is not accepted evidence.

The existing sandbox Chrome profile was verified after the user restarted it;
cookies were not read or copied and no account was provisioned. Local learner,
Admin and Coach servers were restored using the existing managed launcher.
The side browser has a separate expired session and is not claimed signed in.

The initial Progress/sound QA scripts reused their same-day capture folders;
those rerun captures are local development snapshots, not immutable release
evidence. Scripts now create separate run folders and retain the exact target ID
returned when creating their own tab. Borrowed tabs have no cleanup ownership.
Sound restoration must pass local-storage readback before a proof can report it.
Five transport/source-contract tests and three syntax checks passed for these
QA-helper changes; the revised scripts have not been browser-rerun by root.
Older duplicate tabs without recorded creation IDs were deliberately left alone.

## Subsequent picture-control implementation

The mounted player now uses a reusable native `VideoPlaybackSurface` button over
the picture: mouse, touch, pen and keyboard activate the existing play/pause/replay
path immediately. It retains the video's containment and the existing toolbar.
An outside pointer that dismisses Settings cannot also change playback. Cancelled
and secondary pointers cannot activate it. There are no delayed gesture callbacks;
fullscreen remains on its explicit button/F shortcut, not a new double-click claim.
Independent review caught delayed-gesture edge cases in the first candidate; that
candidate was simplified before final acceptance. The final scoped review has no
Critical/Important findings.

Final Node24.19.0 run: **114 tests passed** across the surface, mounted playback,
adaptive and existing runtime suites; learner TypeScript and scoped ESLint passed.
The mounted preview tests assert real media-element play/pause and no canonical API
writes. Unit coverage alone is not native browser acceptance.

The obsolete Python video QA entry point previously executed even for `--help`
and selected an arbitrary existing tab. Its interrupted invocation was not accepted
as evidence. It is now an inert help-only compatibility shim; **10 safety tests**
pass under dependency/process/network/file-write traps, independently re-run.
A new Python surface proof failed during CDP connection; its incomplete record
is retained in `screenshots/video-surface-v4iq29td/proof.json`. That unaccepted new
script was removed, and the existing explicit-opt-in native CDP proof was extended
instead. Failed/partial attempts are not counted as browser passes.

The first native surface run, `native-adaptive-video-2026-09-08T13-30-57-442Z`,
stopped at activity loading before any interaction. Its failed record and loading
capture are preserved. A subsequent fresh run on the user's reachable Chrome
passed **26 checks**: [picture-control browser proof](screenshots/native-adaptive-video-2026-09-08T13-39-59-988Z/proof.json).
Real mouse and Space activation, emulated touch play/pause, Settings dismissal
without click-through, actual 360/1080/2160p decoding, quality retention, seek,
fullscreen and contained player/settings at 320/390/1440px all passed. Eleven
captures were saved; root visually inspected mobile player and desktop Settings.
The exact newly created test tab was confirmed closed; existing tabs were untouched.
Activity state/revision/actions stayed unchanged. Main-document guards observed no
write or external request attempts; they are not a browser-wide network certificate.
The run recorded dropped video frames on this development machine, so it does not
establish smooth-playback performance or a production performance acceptance.
Independent source review closed the proof's stage-label and cleanup findings.

The later production-capable media composition has [separate PostgreSQL/byte proof](20260908_PUBLIC_FILM_RUNTIME_AND_POSTGRESQL.md).
Real deployment, Safari, long-film performance,
network-induced adaptive switching and full accessibility acceptance remain open.
