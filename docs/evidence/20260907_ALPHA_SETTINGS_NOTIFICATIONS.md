# Alpha settings and notifications refinement — 7 September 2026

## Scope and authority

This is a focused implementation within the existing Alpha overhaul, in the single
`codex/local-staging-dev-bridge` worktree. It follows the approved
[learner refinement direction](../workflows/v0.1-alpha-experience/00-start-here/learner-refinement-direction-2026-09-07.md).
The user's screenshots inform information hierarchy, not new account permissions,
notification data, metrics, or provider capabilities. Their private screenshots are
not copied into release evidence. The supplied AC/CA kit, Inter typography, and
existing semantic theme tokens remain in use.

The workflow-ui-production skill shaped the mounted-route tracing, conditional
state coverage, disjoint ownership, and before/after verification. Frontend-design
was applied as restrained, compact UI refinement, without replacing the selected
brand or inventing a new theme.

## Implemented

- `/settings` still mounts `SettingsRuntime`, with the original identity-first
  authorization, independent learning-profile error handling, stale-response
  guards, session expiry, offline read notices, and bounded draft cleanup.
- The five existing categories are now searchable by category and control keywords.
  Exactly one category panel is visible and accessibility-exposed. Existing
  category operation owners remain mounted beneath native `hidden` wrappers so
  pending work and recovery cannot be discarded by navigation. Desktop uses a compact side navigation;
  mobile uses category/detail navigation with an explicit **All settings** return.
- Existing `#verified-account`, `#appearance`, `#learning-setup`,
  `#security-privacy`, and `#session` deep links remain. Category changes update
  browser history without a new API navigation. Back/forward restores the category;
  selected headings and mobile return controls receive deliberate focus.
- Appearance uses compact labeled native selects for theme, accent, density, and
  motion. Coordinated presets are behind a disclosure. The same existing store
  applies changes immediately, saves when allowed, and explicitly distinguishes
  session-only changes when browser storage fails. No separate save button or
  unsaved account draft is fabricated.
- The notification bell shows one compact, honest unavailable message and a useful
  **Go to My Learning** action. Repeated badges, large empty artwork, and engineering
  jargon are removed. Existing Escape, outside click, close, and focus restoration
  remain owned by the shell. The notification route uses the same truthful copy.
- No unread count, “all caught up” state, notification preference, notification
  history service, account edit API, permission, score, streak, or new capability
  has been invented. Connected-empty and disconnected resources remain distinct.

## Tests

- Initial focused Vitest: **32 passing tests across four files**, including four mounted
  React cases for category/hash/focus, deep links/history, blocked storage, and
  learner-role gating.
- Full learner Vitest: **532 passing tests across 38 files**.
- Learner TypeScript check: passed after using the normal JSX invocation in the new
  mounted test (the first new-test createElement overload was corrected).
- Learner ESLint: passed with zero warnings before the final small style/copy
  refinement; final focused validation is recorded below.
- QA script Ruff and formatting: passed. `git diff --check`: passed.

## Browser evidence

Environment: existing `http://learner.localhost:3100`, local development build,
isolated headless Chrome **152.0.7977.82**, fresh contexts, synthetic API reads,
no imported user cookies/storage, service workers blocked, all server writes and
unrecognized API reads blocked. This is local fixture UI evidence, not staging,
production, native-device, PWA-offline, or production-performance proof.

All captures are under `screenshots/alpha-settings-2026-09-07/`:

| Run                                        | Purpose                                                                     | Result                                                                                                                           |
| ------------------------------------------ | --------------------------------------------------------------------------- | -------------------------------------------------------------------------------------------------------------------------------- |
| `before/run-20260907T133353Z`              | Existing mounted settings, bell, notifications route at 390/1440 light/dark | 4 cases, 12 images; captured before product edits                                                                                |
| `after/run-20260907T133909Z`               | First interaction/layout pass                                               | Diagnostic history: capturing before hydration caused Playwright caret-hiding mismatch; harness now waits for identity effects   |
| `after-final/run-20260907T134148Z`         | 320/390/768/1440, light/dark, reduced motion                                | 8 cases, 48 images, no failures, overflow, page errors, writes, or unknown reads                                                 |
| `after-verified/run-20260907T134628Z`      | Final small-screen styling and added injected recovery states               | Eight layout/interaction paths passed; two storage-injection harness errors preserved, then corrected                            |
| `acceptance/`                              | Intermediate enhanced harness                                               | Interrupted after discovering callback-argument mismatch; no product failure inferred                                            |
| `acceptance-verified/run-20260907T134943Z` | Enhanced matrix                                                             | Diagnostic strict locator matched Next's route announcer as well as the actual appearance alert; scoped to the Appearance region |
| `acceptance-final/run-20260907T135203Z`    | Matrix before independent lifecycle review                                  | 8 cases, 54 PNGs (3,342,281 bytes), zero failures; 146 solid-color contrast measurements, min 6.04:1 light / 8.54:1 dark         |
| `mobile-normalized/run-20260907T135520Z`   | Normalized scroll before mobile full-page captures                          | 2 cases, zero failures; avoids showing fixed chrome at a native-select/hash retained scroll offset                               |

The harness asserts keyboard activation of filtered category links, active-panel
count, category heading focus, stored accent values, browser back, no-results
recovery, direct links, mobile return focus, bell Escape/focus restoration, and
zero horizontal overflow. Enhanced checks inject a learning-profile 503, retry to
real rendered fixture data, and block browser storage to verify truthful local
feedback. Review-fix coverage additionally fulfills a synthetic logout POST inside
the isolated browser route handler; the request never reaches a server, and its
count is asserted to remain one after local-cleanup retry. It does not sign out or
modify a real account.

## Independent review corrections

The independent reviewer identified two Important lifecycle regressions that were
not covered by the initial layout matrix: keyed category remounting discarded
pending sign-out/cleanup-only recovery and discarded appearance's session-only
storage warning. These findings invalidated release acceptance despite the earlier
matrix being green.

Correction: all existing category owners now remain mounted while native `hidden`
exposes only the selected panel. This preserves pending operations, confirmed
server-revocation state, retry type, appearance feedback, and storage errors across
category changes. No extra API reads or hidden interactive controls are introduced.
The appearance scope note now describes browser scope without claiming successful
saving. The shared SignOutControl also disables its ordinary action after local
sign-out/cleanup-only state and guards against a repeated logout; cleanup retry
retains its existing no-server-request path.

Mounted regression tests cover pending sign-out → another category → Session,
confirmed logout with unavailable storage → another category → Session → local
cleanup retry, and blocked appearance persistence → another category → Appearance.
The first post-fix focused/broad regression run passed **150 tests across five
files**. Post-fix TypeScript, focused ESLint, Ruff and diff checks passed.

Actual-browser post-fix reproduction:
`review-fixes/run-20260907T140223Z` passed **4/4 cases** (320/1440, light/dark),
with **34 PNGs / 2,267,059 bytes** and **104 solid-color contrast measurements**.
Minimum measured contrast stayed 6.04:1 light / 8.54:1 dark. Each light case
intercepted exactly one synthetic logout, retained the cleanup-only message across
Appearance → Session, and retried local cleanup without a second logout. Both
appearance warning retention and absence of a false saved claim were asserted.
No browser page errors, real server writes, or unknown API reads occurred.

Reviewed post-fix screenshots:

- [320px retained cleanup recovery](screenshots/alpha-settings-2026-09-07/review-fixes/run-20260907T140223Z/fixture-320-light-session-cleanup-recovery-retained.png).
- [Desktop retained appearance warning](screenshots/alpha-settings-2026-09-07/review-fixes/run-20260907T140223Z/fixture-1440-light-appearance-recovery-retained.png).
- [Desktop compact appearance](screenshots/alpha-settings-2026-09-07/review-fixes/run-20260907T140223Z/fixture-1440-light-appearance.png).
- [320px notification popover](screenshots/alpha-settings-2026-09-07/review-fixes/run-20260907T140223Z/fixture-320-light-notification-popover.png).

Independent root-requested reconfirmation subsequently closed both Important
findings. Four fresh synthetic mounted-browser cases repeated the pending and
cleanup-only logout transitions, retained appearance failure, mobile history and
focus behavior. Each logout case made exactly one intercepted POST; cleanup retry
never repeated it. Four inactive native-hidden panels were excluded from role
lookup and 18 Tab steps. Category changes caused zero additional API reads,
unknown reads or real writes. Seven focused files / 63 tests passed independently;
no remaining actionable Critical/Important finding was reported.

Final current-code regression: **534 learner tests across 38 files passed**.
All changed learner source/test/CSS files passed Prettier. Final current-code
**full learner ESLint (zero warnings) and TypeScript checks both passed**.

`review-fixes-medium/run-20260907T140456Z` additionally passed **4/4 cases** at
390/768 light/dark on the same post-fix code. Together with the 320/1440 run, all
eight responsive/theme combinations pass after the lifecycle correction. These
two `review-fixes*` runs supersede earlier captures for current implementation
acceptance. Earlier successful, failed, and interrupted runs remain intact as
history; they must not be substituted for the post-fix evidence.

Combined post-fix evidence is **58 screenshots / 3,661,851 bytes**, plus two JSON
reports and **166 solid-color text-contrast measurements**. The 390/768 run has
24 PNGs / 1,394,792 bytes. All eight cases have zero page errors, unknown reads,
real server writes, and horizontal overflow. The two synthetic logout responses
are explicitly counted in fixture metadata and never reach the API server.

## Remaining release gates

Independent review, exact candidate packaging, staging verification, and release
filing remain root-orchestrator responsibilities. This slice is not a complete
notification backend, full-profile redesign, Academy Studio authoring, or whole
Alpha acceptance. No commit, push, deployment, server restart, or data mutation was
performed by this implementation lane.
