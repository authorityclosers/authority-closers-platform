# Learner Video Player Phase 1 — Implementation Evidence

**Status**: bounded implementation evidence; production activation and browser release approval remain out of scope.

**Worktree**: `D:\Projects\authority-closers-platform-video-player-phase1`

**Branch**: `codex/video-player-phase1`

**Base**: `origin/main` at
`cd2711ddd18ea3360dc7a9e689f90de9136c39f7`

## Controlled source grounding

The implementation followed the repository source-fetch order and the learner
video/accessibility controls in the local controlled-source register. Relevant
source IDs were Master Index, BRD, AC-IMP-00, AC-IMP-01, AC-IMP-03, AC-IMP-04,
AC-IMP-05, PRD, IA, UX Research, UX States, UI System, SRS, Data/Tenancy,
API/MCP, Security, QA, DevOps, Admin, Telemetry, ADR/Risk, and AC-UXA-01.
The local learner video workflow contract is Direction B — Momentum Workshop
and keeps canonical progress, media authorization, and recovery state
server-owned.

## Delivered bounded slice

- `resolveApprovedMedia` now fails closed for manifest-only, HLS/DASH-like, or
  non-progressive delivery. Explicit media and quality options must carry the
  `progressive` protocol, an approved `video/mp4` or `video/webm` content type,
  and an already-authorized source URL. Phase 1 does not activate HLS, DASH, a
  provider, a CDN, or a manifest resolver.
- Optional playback rates and quality renditions are normalized from an
  upstream authorized media adapter. No default speed list is invented. A
  quality option is accepted only with a non-empty server-supplied delivery
  URL and a stable ID; the current `ActivityMediaDescriptor` has no per-rendition
  URLs, so the production adapter renders no quality menu until that capability
  is explicitly supplied.
- The responsive player retains the existing Clarity/Momentum Workshop system,
  44px controls, safe-area padding, light/dark theme tokens, and reduced-motion
  behavior. The settings surface is presentation-only and explicitly states
  that coverage and completion remain server-determined.
- Captions/transcript disclosure is present for approved media even when timed
  text is unavailable, with an honest unavailable message. Transcript search,
  cue seeking, caption toggling, keyboard shortcuts, and focus return remain
  native/semantic controls.
- Browser offline/online events pause playback, invalidate the current playback
  session, expose an explicit Offline state, prevent canonical writes while an
  epoch is stale, and require an authorization/activity-revision refresh before
  a learner can resume after reconnect. Visibility changes preserve the offline
  state.
- Fullscreen targets the whole player/control container through the standard
  Fullscreen API. The WebKit fallback enables native video controls while the
  browser owns fullscreen. Focus returns to the invoking control when a
  presentation surface closes. Keyboard shortcuts ignore buttons and other
  interactive descendants. No completion or mastery semantics changed.
- `MediaPlayerStressHarness` remains development-only and uses local synthetic
  fixtures plus a fake API; its trace is explicitly non-canonical.

## Validation

- Focused Vitest: `18` tests passed for
  `app/components/learning-loop-runtime.test.tsx`.
- Learner test suite: `28` files and `388` tests passed.
- Repository test suite: `1,044` passed and `130` skipped (PostgreSQL, Docker,
  and opt-in browser/environment checks were unavailable on this host).
- `pnpm run format:check` passed (Prettier and Ruff format check).
- `pnpm --filter @ac/learner-web typecheck` and `pnpm run typecheck` passed.
- `pnpm --filter @ac/learner-web lint` and `pnpm run lint` passed with zero
  warnings.
- `pnpm --filter @ac/learner-web build` and `pnpm run build` passed.
- `git diff --check` passed after restoring generated `next-env.d.ts` files.
- Final rebase onto current `origin/main` at `cd2711ddd18ea3360dc7a9e689f90de9136c39f7`
  was clean; the incoming commit touched shell notifications/support only.
  Focused tests, learner typecheck, learner lint, Prettier, and diff-check were
  rerun after that rebase. The full suite/build above were run immediately
  before the clean rebase because no player files were changed by it.
- Commands emitted the repository's existing Node engine warning because the
  host runtime was Node `22.17.0` while the repository declares Node `>=24 <25`.

## Explicit non-claims

No provider, CDN, HLS, recording, transcoding, arbitrary media download,
analytics authority, auth/tenancy behavior, canonical progress contract, or
production DB/VPS state was changed. Browser visual/accessibility evidence was
not claimed because this slice was validated without Playwright or an alternate
browser, as required by the task.
