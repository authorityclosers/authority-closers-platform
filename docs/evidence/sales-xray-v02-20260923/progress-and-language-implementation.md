# Progress and report-language integration — 23 September 2026

Candidate only. This record does not claim staging/production deployment or paid-provider acceptance of coaching-v4.

## Implemented

- Reusable processing component with confirmed recording/transcript/conversation/report stages, saved-work receipts, one optional explanation and explicit recovery actions. No fabricated percentage, ETA, cue carousel or continuous analysis animation.
- GET-only observation separated from fresh-upload plan authorization. Restored calls and manual checks cannot quote or accept a plan. Each GET has a 30-second client deadline; this bounds the status request, never provider execution. Connection errors retain last-confirmed facts and do not offer a fresh plan merely because a read failed.
- Queued/running/unknown/held distinctions, latest-stage projection, and partial C4 saved-work handling. A report opens only after transcript/report identity and evidence validation. Old aborted responses cannot change a replacement studio.
- Unchanged-stage notice after a minute of foreground observation, paused while hidden or unable to refresh. Narrow status announcer excludes interactive controls. State transitions honor reduced motion.
- Guest return guidance uses the owner-checked call URL and explains browser-session/retention limits. It does not promise the signed-in Saved calls library to guests or infer ownership from authentication.
- Server-advertised language choices feed explicit quotes. English UI remains unchanged; Hindi + English and Marathi + English are report options only when the configured engine supports them. Mismatched frozen language requires review; saved language comes from an owner-only immutable-plan read, never today's default.

## Backend evidence

Integration commit `4f382bf1` cherry-picks reviewed delegate `ba4e17e7`. New quotes freeze the current settings revision, engine, report language and v4 knowledge-pack hash. Legacy empty-body quote response shapes and receipt fingerprints are preserved. The owner-only GET creates neither commands nor continuation grants. Existing plans preserve their original configuration.

Delegate executed 40 focused unit tests and all 29 cases in both affected PostgreSQL modules, using a source-verified local AudioAtlas build. Ruff formatting/lint and mypy passed on the four modified modules. Database coverage includes default/explicit preferences, replay/conflict, unsupported v3 languages, malformed input, private projections, read-only counts, settings changes and foreign-owner 404. No provider or production calls were made.

## Local frontend verification

At the initial integrated candidate, all 302 frontend tests across 30 files passed, along with frontend lint and typecheck. Focused progress/language coverage includes two-hour identical observations, hidden-page timing, unknown state, partial C4, failed quote/manual check without writes, report verification failures, hung GET recovery, stale unmounted responses and frozen language behavior. Later refinements receive their own final verification below.

Independent review then found interrupted quote/acceptance races. Cleanup now exposes explicit review when approval is unconfirmed; an owner GET can reconcile acceptance only for the same plan ID/fingerprint and cannot demote known acceptance. Added deferred-response tests prove no second acceptance, no silent re-quote and no stale prompt after server commit. Report language labels additionally require the plan's completed report-run ID to match the validated displayed report. The final affected studio/report-contract suite passed 92 tests; typecheck and targeted lint passed again. Guest-link navigation is tested as rendered behavior.

Chrome browser checks used a private loopback fixture API that refuses every non-GET request. They are visual/interaction checks, not live-provider or real-database evidence.

| Viewport/state | Observed result |
| --- | --- |
| 390×844, running C4 | No horizontal overflow; the full card can scroll naturally. Keyboard brings 44-pixel actions above fixed navigation. |
| 320×740, unchanged and held C4 | No horizontal overflow. All recovery actions reachable; long action labels wrap. Smallest measured control height exceeded 44 pixels. |
| 1024×600, running C5 | No horizontal overflow; short-height layout scrolls. Reduced-motion emulation produces zero-duration stage transitions. |
| 1440×900, running C5 | Entire processing card fits: x363–1323, y191.5–772.3; primary status button is 44 pixels high. |
| 720×450 | No horizontal overflow at dimensions equivalent to a 1440×900 desktop at 200% layout zoom. Actual browser zoom/text-only zoom is not claimed. |
| HTTP503 and browser offline/reconnect | Last-confirmed stage remains; separate connection warning appears and clears after successful refresh. No provider mutation is sent. |

Visual testing found and fixed a real top-clipping defect in a vertically centered, internally scrolling container: `justify-content: safe center` permits overflow toward the bottom. It also corrected inherited center text alignment and the guest-library return promise. Temporary viewport, offline and reduced-motion emulation were reset.

The cloud-generated desktop/mobile references and their hashes are retained in the private orchestration ledger. The implemented progress hierarchy follows those references; the broader existing shell is not yet claimed to match the complete v0.2 visual design. No human usability trial or universal device guarantee is claimed.

Research rationale, primary sources, cloud/local evidence boundaries and falsification criteria: [progress research handoff](progress-research-handoff.md).
