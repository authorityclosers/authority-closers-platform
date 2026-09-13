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
spans, findings with at least one evidence span, all dimensions observed with the
observed subset shown separately, and the existing score publication hold. A
zero is shown as zero when the contract provides that fact; `Not available` is
reserved for missing data. The source weights total 95 while the source
declares 100; this remains an explicit hold and is not presented as an official
score, percentile, badge or streak.

## Implemented behavior

- Added a compact language selector in the actual mounted header. Interface
  step labels, evidence navigator labels, and practice prompt copy switch
  modes; report content is never machine-translated or relabelled.
- Added an approved-stage rail for the three plan stages exposed by the DTO
  (C2/C4/C5). It marks completion only when `report_ready` is true, marks the
  server-reported current stage as in progress, and labels per-stage receipts as
  unavailable because the API does not return them. It does not infer C1–C6
  completion or fabricate percentage progress.
- Added source-derived report measurements and a visible score hold.
- Added a browsable source-moment navigator. Each card uses an existing
  source-bound evidence span, seeks the authorized audio element to the exact
  start time, attempts playback, exposes `aria-pressed` selection state, and
  gives visible recovery when playback is rejected or the source element is
  unavailable.
- Added a single evidence-backed practice focus based on the first report
  improvement, without inventing XP, streaks, scores or completion claims.
- Added responsive styles for 320px reflow and reduced-motion behavior for the
  moment-card microinteraction.
- Added a recovery action for blocked/failed report reads that resets only the
  local journey; saved workspace access and any server-side run remain intact.

## Verification receipts

| Acceptance item                                   | Method                                                                                                                                                            | Environment                                                                                                                                                         | Observed result                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                            | Status |
| ------------------------------------------------- | ----------------------------------------------------------------------------------------------------------------------------------------------------------------- | ------------------------------------------------------------------------------------------------------------------------------------------------------------------- | ---------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- | ------ |
| Existing behavioral workflow remains source-safe  | `pnpm --filter @ac/sales-xray-web test --run`                                                                                                                     | Vitest 4.1.11, Node 24.19.0                                                                                                                                         | 42 tests passed                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                            | pass   |
| Type contracts remain valid                       | `pnpm typecheck`                                                                                                                                                  | `apps/sales-xray-web`, Node 24.19.0                                                                                                                                 | `tsc --noEmit` passed                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                      | pass   |
| Lint remains clean                                | `pnpm lint`                                                                                                                                                       | `apps/sales-xray-web`, Node 24.19.0                                                                                                                                 | ESLint completed with zero warnings                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                        | pass   |
| Production candidate compiles                     | `pnpm build`                                                                                                                                                      | Next 16.3.3, Node 24.19.0                                                                                                                                           | Compiled, typechecked, static routes generated                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                             | pass   |
| Mounted complete report and language modes render | `SALES_XRAY_BASE_URL=http://127.0.0.1:3188 with_server.py --server "pnpm --dir apps/sales-xray-web exec next start --hostname 127.0.0.1 --port 3188" --port 3188` | Next production `next start` from the local build on a verified-unused loopback port, headless Chromium, Node 24.19.0, source-bound API fixtures, 1280px then 320px | Complete report opened; moment seek setter exercised; rejected and unavailable playback recovery visible; all four modes switched; mobile header bounding boxes stayed inside the header with no horizontal overflow                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                       | pass   |
| Screenshot receipts                               | Browser smoke script                                                                                                                                              | Fixture QA; generated silence only; no provider/private audio                                                                                                       | [report-en-desktop.png](D:/AC-authority-closers-release-audit/sales-xray-live-ux-20260913/report-en-desktop.png), [report-en-mobile.png](D:/AC-authority-closers-release-audit/sales-xray-live-ux-20260913/report-en-mobile.png), [report-hi-desktop.png](D:/AC-authority-closers-release-audit/sales-xray-live-ux-20260913/report-hi-desktop.png), [report-hi-mobile.png](D:/AC-authority-closers-release-audit/sales-xray-live-ux-20260913/report-hi-mobile.png), [report-mr-desktop.png](D:/AC-authority-closers-release-audit/sales-xray-live-ux-20260913/report-mr-desktop.png), [report-mr-mobile.png](D:/AC-authority-closers-release-audit/sales-xray-live-ux-20260913/report-mr-mobile.png), [report-en-hi-mixed-desktop.png](D:/AC-authority-closers-release-audit/sales-xray-live-ux-20260913/report-en-hi-mixed-desktop.png), [report-en-hi-mixed-mobile.png](D:/AC-authority-closers-release-audit/sales-xray-live-ux-20260913/report-en-hi-mixed-mobile.png), [report-playback-recovery.png](D:/AC-authority-closers-release-audit/sales-xray-live-ux-20260913/report-playback-recovery.png) | pass   |

The browser smoke fixture mocked workspace access, a source-bound saved report,
transcript and generated silence. It did not call a provider or upload real
audio. The report fixture is labeled synthetic QA and is not a production or
translation-quality claim.

## Known backend needs

- Add a reviewed translation contract (report locale, translated field
  provenance, fallback and review status) before report prose can be offered in
  Hindi, Marathi or mixed language.
- Add a canonical, approved measurement/KPI contract before more report
  numbers or any published score are exposed. Keep the current 95-versus-100
  hold until the source weights reconcile.
- Extend the processing-plan response with immutable per-stage completion
  receipts if the UI should show completed C2/C4/C5 steps individually. The
  current response exposes only approved stages, `current_stage`, and
  `report_ready`.
- Keep model/provider configuration and administration on the admin side; this
  slice adds no controls or activation path for them.
