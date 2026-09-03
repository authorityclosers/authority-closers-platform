# Learner shell identity and direct-avatar increment

Date: 2026-09-03

Status: implementation candidate. The exact commit SHA, CI run, artifact digest,
staging deployment identity and authenticated staging capture are supplied by
the post-commit release gates; they are not guessed in this file.

## Implemented scope

- The shared learner shell reads the authorized `/v1/me` and
  `/v1/profile/avatar` contracts and presents the resulting display name and
  ready avatar consistently in the desktop header, desktop sidebar and mobile
  drawer.
- A missing or failed avatar renders stable first-name/last-name initials.
  Short-lived avatar delivery is refreshed every four minutes, ahead of the
  current five-minute delivery lifetime. A failed image never leaves a broken
  image artifact in the shell.
- A successful profile-avatar revision updates the mounted shell immediately.
  A generation guard prevents an older initial read from overwriting that
  newer revision.
- The top header control is the single desktop sidebar collapse control. The
  duplicate footer control is removed, while keyboard/wheel scrolling remains
  available and the internal scrollbar is visually concealed.
- Routine navigation actions no longer emit implementation-status toasts for
  sidebar collapse, notifications or help.
- Avatar framing now supports drag-and-drop selection, pointer/touch panning,
  wheel zoom and two-pointer pinch zoom. Keyboard-operable range controls are
  retained behind the secondary `Fine-tune with keyboard` disclosure.
- Dark learner dashboard cards, nested labels, dates, badges, progress tracks,
  practice chips, course rows and upcoming-practice surfaces use semantic
  appearance tokens instead of leaking hard-coded light surfaces or navy text.
- The founder-directed adaptive-learning research is captured separately as a
  non-canonical north-star artifact. It does not create routes, fields, event
  names, scores, providers or release authority.

## Truth and security boundary

- Identity and avatar state come only from authenticated server contracts; the
  client does not invent a learner identity or treat browser state as
  canonical.
- The avatar workflow retains the existing fail-closed storage, validation,
  processing and revision behavior. This increment does not activate an object
  storage provider or claim production uploads.
- Avatar delivery URLs remain short-lived and provider-owned. They are neither
  persisted to local storage nor placed in source control.
- Notifications and help remain honest bounded surfaces. Removing routine
  status toasts does not fabricate notification history or a connected chat
  service.
- The authenticated localhost staging bridge is default-off and was enabled
  only in the running development process with its exact loopback and staging
  origins. It stores the staging session only in ephemeral server memory and
  writes no credential to disk or Git.

## Verification

- `pnpm --filter @ac/learner-web exec vitest run app/lib/direction-a-shell.test.ts app/components/avatar-crop-dialog.test.tsx app/lib/color-contrast.test.ts app/lib/avatar-upload.test.ts`
  -> 4 files / 69 tests passed after review repairs.
- `pnpm --filter @ac/learner-web typecheck` -> passed.
- `pnpm --filter @ac/learner-web lint` -> passed with zero warnings.
- Full candidate run: `pnpm --filter @ac/learner-web test` -> 25 files / 338
  tests passed; `pnpm --filter @ac/learner-web build` -> optimized
  Next build passed and generated all 25 application routes.
- `git diff --check` -> passed.
- Chrome opened the live `http://localhost:3000/login` development build and
  rendered the persistent `DEV · STAGING DATA` bridge indicator. Authentication
  and the protected avatar interaction still require an explicit sign-in by a
  dedicated staging learner; this evidence does not claim that capture yet.
- The workstation uses Node 22.17.0 while the repository declares Node 24.x;
  exact-SHA CI on the declared runtime remains authoritative.

## Independent review

An independent read-only review found two release-blocking issues in the first
candidate: incomplete nested dark-theme coverage and short-lived avatar URLs
without refresh/fallback. It also found an initial-read/upload race and
inconsistent multi-word initials. The candidate now includes semantic nested
dark rules, four-minute refresh with failed-image fallback, a generation guard,
and first/last initials across shell, crop and upload presentation. A focused
re-review remains part of the pre-merge evidence.

## Release boundary

This increment may proceed to a staging candidate only after re-review, the
full learner suite/build, repository checks, exact-SHA CI and the documented
staging deployment controller pass. Production remains governed by the
existing v0.1-alpha production activation gate; this file grants no production
approval.
