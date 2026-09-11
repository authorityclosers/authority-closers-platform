# Practice library clarity — 10 September 2026

Status: local candidate on `7bdd069d4bf00561edcab90b1679666205708185` plus the scoped working-tree delta. Not deployed; no claim of complete v0.2 acceptance.

## Implemented boundary

- The featured start action uses an actual returned set, preferring `next-move` when present. Its title, illustration, prompt count and time estimate come from that set.
- An empty catalogue offers a useful route back to learning, not a broken practice link. Set counts are real and singular/plural copy is correct.
- Practice cards use the existing illustrations and central theme aliases for cobalt, mint, lilac and amber. Unknown accents fall back to cobalt. Format labels distinguish matching, gaps, listening, conversation and other exercises without relying on colour alone.
- Fine-pointer hover and press feedback respect both system and saved reduced-motion preferences. No changes to reward policy, credits, XP, official scoring, permissions or practice completion.

Files: `practice-arcade.tsx`, its CSS module and mounted component tests, plus `app/theme.css` in Learner.

## Local verification

Node 24.19.0, pnpm 11.19.0, Windows, 768 MiB Node heap. The three new regression tests first failed against the previous implementation. After the patch, the four focused suites passed 82 tests. Learner TypeScript, scoped ESLint and Prettier passed.

Normal synthetic learner sign-in in an isolated Chrome context; no injected authentication, tenant or preference state. Browser before/after runs:

- `.tmp/local-platform/learner-practice-before-20260910-015602-549577/proof.json`
- `.tmp/local-platform/learner-practice-after-20260910-020557-086731/proof.json`

After checks passed at 390 and 1440 CSS pixels in light/dark, plus 320 dark: no horizontal overflow or horizontally offscreen visible actions; zero console issues. Keyboard card focus was visible (3 px outline plus offset). Card navigation reached `/practice?set=match` without creating an attempt. Saved reduced motion produced no transform or animation/transition duration. The initial settings were restored.

Root inspected desktop light and mobile dark captures. Reported title/muted-text contrast samples used the ancestor surface, not the new tinted gradients; they are not a complete contrast certificate. Exact new badge colours and independent source review remain separate checks. These are local development-mode checks, not production performance or native-device certification.

## Subsequent integration and regression checks

The durable practice header now links directly to the profile's username and leaderboard section. Preview-only mode does not advertise that durable feature. Independent source review found two issues in the first candidate: saved Full motion was overridden by OS Reduced, and unbroken catalogue text could overflow. Both were fixed and the focused re-review reported no remaining Critical or Important findings in this scoped change.

The follow-up normal-auth browser proof is `.tmp/local-platform/learner-practice-regression-20260910-023543-828046/proof.json`. Normal catalogue checks passed at 320, 390 and 1440 CSS pixels with eight cards, no horizontal overflow and no offscreen visible actions. A separately labelled GET-only catalogue fixture supplied unbroken title, description and skill text at those widths; all wrapped without clipping. No attempt or reward was created. OS Reduced plus saved Full retained the 2 px hover response; saved Reduced disabled it with either OS setting. Console issues: zero.

Exact new badge foreground/background calculations passed: default light cobalt/mint/lilac/amber were 6.47/7.17/7.01/7.83; dark were 8.54/11.45/11.53/12.56. The minimum across the checked presets was 5.02 in light and 8.54 in dark. This is limited to those badge pairs, not a whole-app accessibility certification.

The full learner suite subsequently passed 1,438 tests in 75 files. After further community-identity async regressions were added, the focused community/API/Arcade suites passed 33 tests. Learner TypeScript passed after correcting a test catalogue fixture to include its required metadata. These remain local tests, not deployment evidence.

## Subsequent compact Arcade / feedback candidate (10 September, afternoon)

This supersedes the earlier local presentation, not the deployed staging artifact. Base remains `7bdd069d4bf00561edcab90b1679666205708185` plus the dirty worktree; no new release SHA or production acceptance is claimed.

- The hub has a compact standalone `/leaderboard` shortcut. Actual ProfileRuntime disables the embedded ranking read/table; username and academy participation remain profile controls. The dedicated leaderboard remains its own route.
- Cards use original inline SVG scenes, two-column mobile composition, title/time/prompt metadata and a separate 44-pixel information action. Descriptions are available in native dialogs rather than always consuming card space. Dialog controls expose their expanded state and descriptions and return focus on close.
- Credits, XP and weekly activity use separate, themed detail sheets. The weekly progressbar is no longer nested inside a button, and the trigger exposes the real day count and bonus description. A finite arrival treatment highlights the approved 40-credit target; it does not imply the bonus was already earned. Weekly days are not described as a consecutive streak.
- The practice intro now has an illustration/companion scene, a short title and two metadata chips. The existing description, reward explanation, timezone information and companion selection remain available behind Practice details. First-time timezone confirmation and save/retry/conflict handling remain enforced.
- Mounted practice feedback changes the whole task-body surface: success, retry and open-ended reflection have distinct colours, headings and finite companion reactions. Confetti appears only for a server-returned `reference_match: true`, never a failed request or open-ended answer. No official score, reward, rank or credit loss is invented. The server explanation remains visible; the full prompt can be reviewed.
- Matching tiles expose numbered pair relationships, theme-token pair colours, press/selection feedback and finite connection animation. Statements/options and their stable identifiers are preserved. Duplicate right-side assignment and incomplete-submit guards remain intact.
- Direct sound/music controls and the same-origin CC0 background loop are present in the working tree. Root corrected the containing header grid so two audio buttons do not stack inside the old single-button slot. This is not a subjective audio-quality approval.

### Verification of this candidate

- Five focused mounted suites (Arcade, durable engine/rewards, community identity, standalone leaderboard, ProfileRuntime): **85 passed**. New assertions cover true/false/null feedback, no reaction on network failure, secondary details, native-dialog cancel/focus restoration, standalone profile mode and exposed weekly progress semantics.
- Sound controls, sound player and music player: **28 passed**.
- Learner TypeScript and scoped ESLint: passed. Scoped Prettier applied. These tests do not replace viewport/theme/keyboard/motion review in a running browser.
- New screenshots and independent final review: **pending**. Previous screenshots above are not evidence for this later candidate.

### Runtime / release blockers actually observed

- SSH succeeded. `current-staging` still resolves to `4e8d413b828ab750d7c5e20d1a9320d0f427c823`. There is no `current-production` link. Production Learner/Coach return 503; Admin returns the Cloudflare Access redirect, not proof of an authenticated app. Staging Learner returns 200; Coach redirects to sign-in. WordPress apex and `www` both return 200.
- A value-free Infisical presence probe of production `/application` found **0/13** checked database credentials, session/OAuth/email-challenge secrets and canonical learner/operations tenant references. No values were printed, copied from staging, created or overridden.
- All recorded local UI/API process identities were absent. The only listener on port 3100 was Windows `svchost`, with a portproxy rule `0.0.0.0:3100 -> 127.0.0.1:3100`. The exact rule removal was attempted and rejected because administrator elevation is required; the rule remains unchanged.
- Managed local API startup could not complete: PostgreSQL reported permission denied binding `127.0.0.1:55432` (WinError 10013 also reproduced by a read-only bind probe). No excluded TCP range listed includes 55432. No database deletion, direct SQL repair or security-policy workaround was performed. Existing logs were copied to a new `.tmp/local-platform/log-archive/runtime-recovery-*` directory before retrying.
- The launcher port-occupancy checks used a stalled Windows CIM query. `Get-LocalTcpListeners.ps1` now uses the native .NET TCP table, propagates inspection failures, preserves unknown-listener and loopback guards, and is used by the API/UI/PostgreSQL launchers. **18 launcher/TCP/PostgreSQL tests passed**, including an actual ephemeral loopback listener lifecycle; Ruff passed. The scanner's separate PID-ownership check was not weakened.

Still required: restore the managed local runtime, inspect these exact views at 320/390/768/1440 in light/dark/reduced motion, complete the profile-photo save diagnosis, exercise real long-video upload/publication/authorized playback, finish the independent review, package the exact accepted artifact, then staged and production authenticated acceptance. The requested long test video in Dipak’s free course has **not** been attached by this follow-up. Production configuration and consent/provider gates remain mandatory.

### Later runtime recovery (supersedes the local blocking status above)

The user removed the conflicting forwarding rule. Ordinary PowerShell 7 startup
then restored PostgreSQL, API, Learner, Admin and Coach. The compatibility launcher
now handles Windows PowerShell 5.1 and selects installed Node 24 automatically.
Real normal sign-in passed on all three local apps; a real synthetic learner
photo upload completed and its decoded image persisted after reload. See
[`20260910_LOCAL_STARTUP_RECOVERY.md`](20260910_LOCAL_STARTUP_RECOVERY.md) for exact
scope and proof. No remote release or long-video attachment is implied by this
local recovery. Browser verification of the latest learning/Arcade views and
the remaining release gates are still required.

### Learner library / course-path visual polish (10 September, afternoon)

The mounted learner library and course path received a bounded presentation
pass in `learning-runtime.tsx`, `learning-course-card.tsx`, the mounted
`LearningModules` region of `learner-runtime.tsx`, `learning-journey.module.css`,
and `course-surfaces.css`. The unsupported Saved tab and its unavailable notice
are omitted from the rendered library; mobile-only breadcrumbs are hidden while
desktop route navigation remains; next-action copy is plain-language; and the
library/path gradients use existing theme tokens. Server-returned titles,
progress, access, offline, retry and session states remain unchanged.

Focused learner course-surface and mounted-journey suites passed **97 tests**;
learner TypeScript, scoped ESLint, Prettier and `git diff --check` passed.
Fresh normal synthetic learner sign-in plus a same-origin, read-only headless
proof passed at 320, 390, 768 and 1440 CSS pixels in light and dark themes:
`.tmp/local-platform/new/learning-visual/20260910T083005386820Z/proof.json`.
The proof recorded 2 real enrolled course cards, 4 modules and 5 activities;
Saved and its unavailable copy were absent; mobile breadcrumbs were `display:
none` while 768/1440 desktop breadcrumbs remained visible; and the course
overview next action was visible in the first viewport at every requested size.
No learner attempt, completion or reward was created, and no remote release is
implied.

### Later real Arcade acceptance and mobile regressions

Root executed the launcher through actual Windows PowerShell 5.1 again: it handed
off to installed PowerShell 7 and verified all three existing local apps without
elevation, PATH setup or restarting healthy owned processes. This supersedes the
user's pasted old PowerShell-version failure for this implementation worktree.

`scripts/prove-local-arcade-feedback.py` uses normal synthetic learner sign-in,
the real local API, a same-origin browser request guard and fresh headless
Chromium. Its matrix covers hub, intro, matching, retry and success at 320x740,
390x844, 768x1024 and 1440x1000 in light/dark. Theme and reduced-motion emulation
are layout inputs, not proof of the Settings preference workflow or full motion.

Initial runs encountered a loading timeout and a sign-in navigation timeout with
no captured JavaScript error. These did not reproduce on the later stable runs;
their original cause is not established. They were not fixed by restarting the
services or bypassing authentication. A later run exposed a real 320px defect:
the decorative Arcade gradient extended the page to 330px and the reward grid
wrapped the two-digit balances. The pseudo-element now stays within its owner;
the phone grid uses a 28px icon, a smaller gap and aligned number column. There
is no global overflow-clipping workaround.

Accepted evidence:
`.tmp/local-platform/new/arcade-feedback/20260910T085826775671Z/proof.json`

- All **40 viewport/theme/state captures passed** document and session-body
  horizontal containment, applicable footer bounds and single-line real reward
  values. The synthetic learner balances remained server-returned 30 credits,
  90 XP and 2 weekly practice days.
- The weekly sheet opens and returns keyboard focus to its trigger. The trophy
  shortcut points to the standalone `/leaderboard` route.
- A real matching attempt submitted deliberately wrong pairs, displayed retry,
  allowed correction, displayed success for the server-confirmed reference match,
  and restored that confirmed feedback after a page reload. This creates only
  synthetic local attempt/response history; it does not complete the set or claim
  new rewards, official assessment scores or course progress.
- An intermediate run passed through retry but stopped on an ambiguous test
  selector: paired statement accessible names include their selected question.
  The harness now scopes question selection to the right-hand column. The product
  interaction itself was not changed to make the test pass.
- Root visually inspected the corrected 320px light hub, 390px dark success,
  1440px matching screen and preceding 320px retry capture. Screenshot snapshots
  do not establish animation timing, sound quality or physical-device behavior.
- Six focused practice presentation/engine/audio/music suites: **114 passed**.
  Kenney retry-cue integrity and its independent review are separately recorded by
  the video/audio coordinator. Success/retry audio follows actual reference state;
  muted, open-ended and failed-request paths do not emit a feedback cue.

This is an uncommitted local candidate. No new staging or production deployment,
WordPress change, long-video attachment, production performance measurement or
Drive screenshot upload is implied. Full release gates and the global free-course
media publication application remain separate unfinished work.

#### Independent proof correction and accepted rerun

Independent review found that the earlier `20260910T085826775671Z` proof's
"passed" status overstated theme coverage: four files labelled dark-320 recorded
the light document theme. That run proves only 36 theme-accurate captures. Its
40-view acceptance claim above is superseded by the rerun below; the original
artifact is retained. The reviewer found no Critical/Important issue in the
scoped decorative-inset and phone-grid CSS changes.

The harness now asserts the requested and captured theme match, reduced-motion
emulation is active and exactly three reward values were found on each hub
capture. System-media listeners settle before the declared theme input. It fails
on page errors and unclassified request failures. An aborted GET is classified
only when it spans observed navigation or has an exact-path HTTP 200 counterpart
in the same run; failed writes and other errors are not waived. Exact paths are
compared in memory, and synthetic record IDs/private media object paths are
redacted in saved diagnostics. Intermediate runs with incomplete cancellation
classification remained failed, even though their layouts passed.

Final accepted local evidence:
`.tmp/local-platform/new/arcade-feedback/20260910T091126219472Z/proof.json`

- **40 captures; 0 theme mismatches; 0 JavaScript page errors.** Two cancelled
  practice-progress GETs each had an exact-path HTTP 200 counterpart and are
  explicitly classified in the proof. This is not a zero-cancellation claim.
- Every hub capture found exactly three single-line values for this actual
  synthetic learner (30, 90, 2). Larger balances are not covered by this run.
- The retry screen no longer presents the reference answer's potentially
  congratulatory prose as a description of the wrong response. It states that
  the response differs from the reference, and preserves the original server
  explanation behind a default-closed `Reference explanation` disclosure.
  Correct/open-ended explanations and canonical response semantics are unchanged.
- Root visually inspected the accepted 320px dark retry and the agent's final
  320px light course-library action placement. Focused practice tests were rerun:
  **114 passed**, including the retry-copy/disclosure assertion. Learner TypeScript,
  scoped Prettier, Ruff check/format and whitespace checks passed.

Final independent re-review disposition is recorded when returned. These checks
do not certify every exercise, full-motion timing, audio taste, all balances or
production serving performance.

Independent re-review returned **no remaining Critical/Important findings** in
this bounded Arcade code/proof delta. It confirmed all 40 requested themes,
non-vacuous three-value checks, zero page errors, explicit cancellation
classification, diagnostic redaction and the truthful retry-copy/disclosure
boundary. The larger-balance and broader release limitations remain unchanged.

### Learner library phone first-action follow-up (10 September, 14:30 UTC)

The narrow collection follow-up keeps the single server-backed course CTA above
the fixed learner bottom navigation at the requested phone sizes. Phone-only
header/filter/card spacing was tightened, the CTA is ordered before secondary
next-action/progress details, and the late legacy artwork rules are overridden
so the course eyebrow remains fully visible. The course title, enrollment,
progress values, access states and route target remain service-returned.

Fresh normal synthetic learner sign-in and same-origin headless Chromium passed
at 320x740 and 390x844 in light and dark themes. The first real course was
`Authority Closers Free Course`; its `Continue course` link ended at y=583.72
against the fixed-nav top at y=680 on 320x740, and at y=589.44 against y=784 on
390x844. Evidence: `.tmp/local-platform/new/learning-visual-followup/20260910T090306000424Z/proof.json`
and its four PNG captures. The capture deliberately used no API mocks and
performed no learner mutation.

Scoped learner surface and mounted-journey suites passed **97 tests**;
learner TypeScript, scoped ESLint, Prettier and `git diff --check` passed.
No server restart or remote release is implied.
