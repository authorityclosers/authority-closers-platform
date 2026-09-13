# Sales Xray live UX slice — 2026-09-13

Status: local implementation evidence for `codex/sales-xray-live-ux-20260913`.
This is fixture QA and local runtime evidence; it is not staging or production
release evidence.

## Acceptance contract

The mounted route is `/` (`app/page.tsx` → `StandaloneStudio` →
`CallStudio`). The bounded slice covers the learner-facing upload → approved
processing → report journey. Model and provider administration remain outside
this surface.

The report contract currently supplies a source-bound transcript, findings,
eight dimension states and nine report sections. It does not supply a report
locale, reviewed Hindi/Marathi translations, a canonical KPI payload, or an
approved published score. The UI therefore exposes three display modes for
interface labels only: English-only, Hindi/Devanagari, Marathi/Devanagari and
English + Devanagari mixed. A visible report notice states that report text
remains in its server-provided language.

Report cards are derived from the received payload: unique timestamped source
spans, findings with at least one evidence span, observed dimensions out of the
eight supplied dimensions, and the existing score publication hold. A zero is
shown as zero when the contract provides that fact; `Not available` is reserved
for missing data. The 95 / 100 source-weight mismatch remains an explicit hold
and is not presented as an official score, percentile, badge or streak.

## Implemented behavior

- Added a compact language selector in the actual mounted header. Interface
  step labels, evidence navigator labels, and practice prompt copy switch
  modes; report content is never machine-translated or relabelled.
- Added a server-stage rail for C1–C6 that marks only stages implied by the
  server's current stage or completed state. It does not fabricate percentage
  progress.
- Added source-derived report measurements and a visible score hold.
- Added a browsable source-moment navigator. Each card uses an existing
  source-bound evidence span, seeks the authorized audio element to the exact
  start time, attempts playback, and exposes `aria-pressed` selection state.
- Added a single evidence-backed practice focus based on the first report
  improvement, without inventing XP, streaks, scores or completion claims.
- Added responsive styles for 320px reflow and reduced-motion behavior for the
  moment-card microinteraction.

## Verification receipts

| Acceptance item | Method | Environment | Observed result | Status |
| --- | --- | --- | --- | --- |
| Existing behavioral workflow remains source-safe | `pnpm --filter @ac/sales-xray-web test --run` | Vitest 4.1.11, Node 22.17.0 | 42 tests passed | pass |
| Type contracts remain valid | `pnpm typecheck` | `apps/sales-xray-web` | `tsc --noEmit` passed | pass |
| Lint remains clean | `pnpm lint` | `apps/sales-xray-web` | ESLint completed with zero warnings | pass |
| Production candidate compiles | `pnpm build` | Next 16.3.3 | Compiled, typechecked, static routes generated | pass |
| Mounted route and language control render | `tests/browser_call_studio_ux.py` via `with_server.py` | Next dev, headless Chromium, API fixtures, 1280px then 320px | English-only, Hindi/Devanagari, Marathi/Devanagari and English + Devanagari mixed labels switched; 320px main remained visible | pass |
| Screenshot receipt | Browser smoke script | Fixture QA; no private audio | [sales-xray-live-ux-20260913.png](D:/AC-authority-closers-release-audit/sales-xray-live-ux-20260913.png) | pass |

The browser smoke fixture mocked only workspace access and an empty saved-call
list. It did not call a provider or upload real audio. Report metrics and
source-moment behavior are covered by the mounted-component Vitest test using
the existing source-bound fixture contract.

## Known backend needs

- Add a reviewed translation contract (report locale, translated field
  provenance, fallback and review status) before report prose can be offered in
  Hindi, Marathi or mixed language.
- Add a canonical, approved measurement/KPI contract before more report
  numbers or any published score are exposed. Keep the current 95-versus-100
  hold until the source weights reconcile.
- Keep model/provider configuration and administration on the admin side; this
  slice adds no controls or activation path for them.
