# Authority Closers — Learner Video-Player Implementation Evidence

**Worktree Branch**: `codex/antigravity-video-player`  
**Date**: 2026-09-03  
**Auditor Reference**: AC-GOV-AUD-001  
**Controlled Source Baseline**: Pinned manifest in `docs/traceability/CONTROLLED_SOURCE_REGISTER.md`  

---

## 1. Executive Summary & Boundaries

This implementation slice delivers a production-grade, responsive learner video experience for Desktop Chrome, Mobile/PWA, Android-compatible PWA, and iOS Safari/PWA within the isolated worktree `antigravity-video`.

### Strict Guardrail Adherence
- **Fail-Closed Behavior**: Playback, scrubbing, and evidence generation are strictly blocked when lesson media is absent, blocked by policy, or when the learner is offline.
- **Provider Activation Inactive**: S3, Cloudflare R2, MinIO, video transcoding workers, and CDN edge provisioning remain completely disabled. No cloud credentials or secrets are accessed or required.
- **Progress Integrity**: No client-side progress invention or local mastery state mutation. Completion is recorded exclusively via server-resolved evidence submission through `LearnerApi`.
- **Light-Default Design System**: All UI states adhere to the Clarity / Momentum Workshop design language (Direction B) with dark player stage, high-contrast accessible controls, and responsive layout scaling.

---

## 2. Controlled Source Traceability

| Control ID | Controlled Source Document | Implementation Mapping |
| :--- | :--- | :--- |
| **AC-IMP-00** | `SRC-000-control-authority.md` | Single-source authority preserved; no external mutations outside worktree. |
| **AC-IMP-01** | `SRC-010-implementation-controls.md` | Explicit capability checks (`canStartPlayback`, allowed action validation). |
| **AC-IMP-02** | `SRC-020-product-experience.md` / `SRC-021` | Direction B Momentum Workshop layout, responsive mobile PWA adaptations. |
| **AC-IMP-03** | `SRC-030-state-interface-assurance.md` | Three-layer presentation state architecture: ready, playing, buffering, backgrounded, blocked, unavailable, complete. |
| **AC-IMP-04** | `SRC-040-engineering-contracts.md` | Strict integration with `ActivityMediaDescriptor` (`apps/learner-web/app/lib/learner-api.ts`). |
| **AC-IMP-05** | `SRC-050-trust-operations.md` | Non-canonical telemetry observation hook (`onTelemetryEvent`); no telemetry pollution of canonical progress. |
| **AC-GOV-AUD-001** | Audit normalization register | Zero unverified provider integrations, zero test skips. |

---

## 3. Architecture & Delivered Components

### 3.1 `resolveApprovedMedia(activity, explicitMedia)`
- Resolves stream URLs from either explicit props (for testing/harness) or `activity.media` (`ActivityMediaDescriptor`).
- Inspects `activity.media.state`:
  - If `"blocked"`: returns `{ media: null, state: "blocked", reason: descriptor.reason }`.
  - If `"approved"` and `playback_available` and stream delivery exists: maps ready captions (filtering out superseded/retired tracks) and returns `{ media, state: "approved" }`.
  - If absent or unapproved: returns `{ media: null, state: "unavailable" }`.

### 3.2 Accessible Player Shell (`VideoViewer`)
- **Desktop, Mobile, iOS Safari & Android Support**:
  - `playsInline`, `preload="metadata"`.
  - WebKit fullscreen fallback (`webkitEnterFullscreen`) for iOS Safari alongside standard HTML5 Fullscreen API.
  - HTML5 Picture-in-Picture (`requestPictureInPicture`) feature detection.
  - Mobile touch targets meet the 44×44px minimum touch target size.
  - Safe-area insets (`env(safe-area-inset-bottom)`) applied for PWA / notch displays.
- **Fail-Closed Presentation Stages**:
  - `LockedMediaStage`: Rendered when media is unavailable, informing learner that watch evidence cannot be submitted.
  - `BlockedMediaStage`: Rendered with `ShieldAlert` badge and explanation when media is policy-blocked.
  - `CompletedMediaStage`: Server-resolved completion state; media playback is locked from finished state.
- **Keyboard Shortcuts (`aria-keyshortcuts`)**:
  - `Space` / `K`: Play / pause
  - `ArrowLeft` / `ArrowRight`: Seek -5s / +5s
  - `J` / `L`: Skip -10s / +10s
  - `ArrowUp` / `ArrowDown`: Volume ±10%
  - `M`: Mute toggle
  - `F`: Fullscreen toggle
  - `C`: Captions toggle
  - `T`: Transcript panel toggle
  - `?`: Keyboard shortcuts guide toggle
  - `Escape`: Close shortcuts guide or transcript panel
- **Reduced-Motion Handling**:
  - CSS `@media (prefers-reduced-motion: reduce)` disables all animations and transitions.
  - Script auto-scroll for active transcript cue respects `prefers-reduced-motion`.
- **Non-Canonical Telemetry**:
  - `VideoTelemetryEvent` emits observation-only events (`video_loaded`, `video_play`, `video_pause`, `video_seek`, `video_rate_change`, `video_volume_change`, `video_fullscreen_change`, `video_pip_change`, `video_captions_toggle`, `video_transcript_toggle`, `video_transcript_seek`, `video_error`).

### 3.3 Interactive Transcript Panel (`CaptionsTranscriptPanel`)
- Clickable timestamps that seek video playback to cue start.
- Active cue highlighted with brand accent border and `aria-current="time"`.
- Instant search filter with clear query affordance.
- Honest fallback message when transcript is unavailable.

---

## 4. Verification Evidence

### 4.1 Focused Test Suite (`vitest`)
```
 RUN  v4.1.11 C:/Users/Suyash/.codex/worktrees/antigravity-video/apps/learner-web

 ✓ app/components/learning-loop-runtime.test.tsx (11 tests) 145ms
   ✓ formats the player clock without inventing progress
   ✓ requires the server action and a writable activity state before playback
   ✓ resolves approved media descriptors safely
   ✓ renders an honest unavailable state when no authorized media descriptor exists
   ✓ renders media only from the explicit authorized descriptor
   ✓ renders media automatically from an approved activity media descriptor
   ✓ fails closed when activity media descriptor is blocked by policy
   ✓ renders BlockedMediaStage with honest messaging and return link
   ✓ renders interactive transcript panel with search, cue seeking, and active state
   ✓ renders keyboard shortcuts guide with standard video navigation keys
   ✓ preserves the server-resolved completed state after media is no longer playable

 Test Files  1 passed (1)
      Tests  11 passed (11)
   Duration  2.87s
```

### 4.2 TypeScript Typecheck (`tsc --noEmit`)
```
$ pnpm --filter @ac/learner-web typecheck
Exit status: 0 (No type errors)
```

### 4.3 ESLint Check (`eslint . --max-warnings 0`)
```
$ pnpm --filter @ac/learner-web lint
Exit status: 0 (0 errors, 0 warnings)
```

---

## 5. Remaining Provider / Gate Blockers

1. **Storage Provider Activation**: S3, Cloudflare R2, MinIO storage configurations remain in unprovisioned state pending infrastructure sign-off.
2. **Media Transcoding Pipeline**: Automated rendition generation (HLS adaptive bitrate ladder) remains disabled pending worker cluster configuration.
3. **CDN Distribution**: CDN Edge endpoints are currently unconfigured; delivery relies on descriptor URLs supplied by the backend.
4. **Canonical Progress Authority**: Mastery and completion remain strictly gated behind backend evidence submission (`LearnerApi.submitEvidence`).
