# Preserve activity recovery across hydration and retry

Date: 2026-09-13 (Asia/Kolkata). Scope: a follow-up to password activity-return
checkpoint `9bfba2c3202e284fdab152f9cedf69cc97e980d3`.

## Browser failure and cause

The full learner suite passed 1,675 tests across 90 files on `9bfba2c`. Actual
390px browser acceptance nevertheless failed in
`canonical-draft-recovery-20260912T210929Z`: fresh registration and verification,
explicit onboarding/enrollment, draft revision 1, failed-save retry to revision 2,
session revocation, password sign-in and automatic return to the exact activity
all worked. The same authenticated person returned, with no browser errors or
blocked requests, but unsaved response C was not restored. The server retained
saved response B at revision 2; no completion state was advanced.

Mounted regression tests reproduced the failure. React StrictMode replays the
hydration effect while its first exclusive `ifAvailable` Web Lock is still held.
The active read can therefore report unavailable. Previously, that result still
marked local hydration complete, allowing the clean-editor persistence effect to
read and delete the recovery copy it had never restored. The separate offline
read-cache purge was not the cause.

## Correction

The activity workspace defers the initial lock request to a cancellable
microtask, so a discarded effect does not acquire the recovery lock. An
unavailable read leaves hydration unverified and prevents automatic persistence
or cleanup. An explicit Retry local recovery control can read the retained copy
later; the control stays inside the collapsed storage notice on clean video
pages. All original locking, retention, scope, fingerprint and revision checks
remain in place.

Retry must also preserve edits made before the retry begins. Recovery hydration
now applies only before the learner's first edit on the mounted editor. A fifth
mounted regression reproduced the earlier retry overwrite and confirms that the
current typed response wins in both the editor and the subsequent recovery copy.

No backend, authentication, consent, membership, enrollment, access, evidence,
progress, database or provider contract changes. This patch does not activate
Google/email/reset continuity or claim a completed course-delivery journey.

## Validation

Receipts are under
`D:/Projects/authority-closers-release-transfer/2026-09-11-recovery`.

- `activity-hydration-red-20260912T211450Z`: two failures and two passing controls
  before product changes, proving StrictMode loss and unavailable-read deletion.
- `activity-hydration-green-20260912T211636Z`: the four new cases passed; an
  existing storage-notice wording assertion failed. The original wording was
  retained in the correction; the failed receipt remains available.
- `activity-hydration-targeted-20260912T211741Z`: 68 focused cases, learner
  TypeScript, formatting and zero-warning scoped ESLint passed.
- `activity-hydration-retry-red-20260912T212045Z`: one failure and four passes,
  proving an edit made before retry could be overwritten.
- `activity-hydration-final-targeted-20260912T212121Z`: all 71 cases in five files
  passed and scoped ESLint passed. TypeScript reached the imposed 384 MiB heap
  ceiling; that failure is retained.
- `activity-hydration-full-validation-20260912T212321Z`: learner TypeScript passed
  with a 640 MiB heap after stopping the managed local apps. The full learner
  suite then passed all 1,680 tests across 91 files with one 384 MiB worker under
  Node 24.19.0. This receipt binds the exact final source/test SHA-256 values and
  supersedes the earlier TypeScript memory-limit failure.

The new tests mount the actual activity workspace with real local-storage
helpers and exclusive, `ifAvailable` lock semantics. They cover normal/StrictMode
restoration, unavailable-read preservation and retry, newer-server conflict
separation, and edit preservation. They assert that hydration performs no server
draft save or evidence submission.

Independent Luna xhigh review confirmed the original P1 and found no actionable
defect in the final two-file correction, including the retry/edit guard.

The exact-checkpoint canonical browser rerun remains pending after this tested
local checkpoint. Browser acceptance must show automatic activity return,
visible C restoration, server B/revision 2 unchanged until explicit save, then
C/revision 3 with unchanged completion and zero browser errors/blocked requests.

## Exact-checkpoint browser acceptance

The canonical browser rerun passed on commit
`2127ee49e2c4d113ff328bbe0b78bde7452ff612`; API readiness returned that same
release identifier. Receipt: `canonical-draft-recovery-20260912T212752Z/proof.json`.
The retained failed receipt above remains part of the history.

At 390px, a fresh synthetic learner registered, verified locally, skipped
onboarding explicitly and enrolled through canonical APIs. Draft A persisted as
revision 1. An interrupted B save retained the response; retry reused its command
identity and persisted revision 2. After a real self-session revocation, saving C
returned 401. Normal password sign-in returned 200 and automatically reopened the
same activity for the same person. The editor visibly restored C from local
recovery, while the server still held B/revision 2. Only explicit Save persisted
C/revision 3. Completion remained unchanged throughout.

All five views had viewport/document width 390px. There were zero page errors or
blocked requests. Screenshots 03, 04 and 05 were visually inspected: the expired
session retains C, the returned activity says local draft restored, and the final
save reports success. This establishes local password-session recovery acceptance;
it does not claim email delivery, live Google authentication or deployment.
