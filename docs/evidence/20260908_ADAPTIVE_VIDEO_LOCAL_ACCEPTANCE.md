# Adaptive video — local implementation and acceptance

2026-09-08. Bounded localhost acceptance passed; this is not alpha-release approval or a VPS deployment.

## Implemented scope

The learner dependency and lockfile pin the official `hls.js` package to **1.7.2**. The [adaptive adapter](C:/Users/Suyash/.codex/worktrees/d2de/authority-closers-platform/apps/learner-web/app/lib/adaptive-video.ts) loads it through a dynamic import only for eligible adaptive playback. The actual [lesson viewer](C:/Users/Suyash/.codex/worktrees/d2de/authority-closers-platform/apps/learner-web/app/components/learning-loop-runtime.tsx) selects an approved signed HLS master, delegates decoding, displays actual rendition choices, and preserves its existing controls and evidence boundary. Native HLS is a capability fallback; progressive fallback is used only when both adaptive decoding paths are unsupported, not to bypass authorization or playback errors. The older staging-over-localhost bridge remains progressive-only.

The backend already provides master, variant, caption and MPEG-TS objects for two pinned public-film fixtures: Big Buck Bunny at 360p/1080p/2160p and Caminandes at 360p/1080p. These are **12-second technical fixtures, not Dipak's instructional content**. This slice does not activate arbitrary uploads, external providers, official scoring, or new course-completion authority.

## Guardrails and review corrections

The [authorized loader](C:/Users/Suyash/.codex/worktrees/d2de/authority-closers-platform/apps/learner-web/app/lib/authorized-hls-loader.ts) uses same-origin credentials, no redirects/cache/referrer, bounded deadlines, cancellation, MIME/length/range validation, and 2 MiB playlist/subtitle and 32 MiB segment limits. Child requests must retain the original tenant/person/session/activity/binding/enrollment/grant/expiry and canonical video namespace. This is withholding logic, **not client-side signature verification**; normal server authorization remains authoritative for every object. Diagnostics are fixed text with no native response/error payload forwarding; signed URLs necessarily remain in private decoder request context, not telemetry.

Review and regression tests corrected:

1. **Reconnect authorization:** no replacement decoder may start while a fresh, same-scope authorization read is unresolved or denied.
2. **Position restoration:** capture position/rate/volume/mute before offline or fatal-error cleanup; restore paused after authorized metadata reload and reapply selected quality. A resumed tracked session begins observing at its restored cursor, never credits the disconnected gap. Cleanup still runs if the error callback throws.
3. **Duplicate retry:** authorization recovery and Retry no longer both recreate the decoder; one successful retry creates exactly one replacement.

## Verification status

**216 tests passed together:** 65 adapter, 67 loader, 18 mounted adaptive-viewer and 66 existing playback tests. Final learner typecheck, scoped source/test ESLint, proof-script syntax check and scoped diff whitespace check passed; test formatting passed. Tracked API mocks preserve complete response contracts.

The [successful native-browser proof](C:/Users/Suyash/.codex/worktrees/d2de/authority-closers-platform/docs/evidence/screenshots/native-adaptive-video-2026-09-07T22-00-47-925Z/proof.json) passes **23 checks** using native CDP mouse/keyboard input: decoded 640×360, 1920×1080 and 3840×2160 HLS, Auto selection/playback, 1.5× speed, mute, captions, seek and fullscreen. Player/settings fit 320/390/1440px without overflow. Screens: [4K desktop](C:/Users/Suyash/.codex/worktrees/d2de/authority-closers-platform/docs/evidence/screenshots/native-adaptive-video-2026-09-07T22-00-47-925Z/quality-2160-desktop.png), [320px settings](C:/Users/Suyash/.codex/worktrees/d2de/authority-closers-platform/docs/evidence/screenshots/native-adaptive-video-2026-09-07T22-00-47-925Z/settings-320.png). Before/after activity remains available, revision 0, actions `[save_draft]`. Main-document guards observed zero mutation attempts/external requests; this is not a worker/browser-wide network certificate.

Preserved failures: [21:54 layout](C:/Users/Suyash/.codex/worktrees/d2de/authority-closers-platform/docs/evidence/screenshots/native-adaptive-video-2026-09-07T21-54-30-788Z/proof.json) required compact mobile controls/settings; [21:57 input](C:/Users/Suyash/.codex/worktrees/d2de/authority-closers-platform/docs/evidence/screenshots/native-adaptive-video-2026-09-07T21-57-59-592Z/proof.json) failed during a moving smooth-scroll click. The proof harness now uses instant scrolling and verifies select focus. Neither failed artifact was overwritten.

Not proven: bandwidth-induced Auto switching, Safari native HLS, browser expiry/revocation/offline recovery, long-session streaming, staging/production deployment, Drive publication or native-app acceptance.
