# Sales Xray upload and processing viewport slice

Date: 2026-09-16. Base: `e62ea3d6c45761afa6af0a5cf4a532cb9907fdda`.
Scope: public Sales Xray guest/account shell, upload/consent, actual processing
stages, paused recovery, initial account access and signed-out saved calls.
This is local compiled-build evidence, **not production/provider proof**.

## Authority and implementation

The user's supplied Sep16 desktop/mobile mockups remain the visual reference:
white canvas, bold navy sans-serif, teal/mint, blue, violet and orange icons,
short copy, one primary viewport and focused detail disclosures. Their sample
scores, report text and controls are not permission to invent backend data.

- Transparent header; floating right-aligned profile; sidebar top is 62.4px.
- Stable shell across file selection, upload, C2, C4, C5 and report handoff.
- Selected file replaces the large drop area; verification and consent stay
  visible. Consent is not duplicated below upload progress.
- Compact phase-aware icons and three factual stage tiles. No fake percentage,
  timer, rotating motivational claims or automatic restart on a held stage.
- Paused recovery preserves the existing transcript/submission; continuing is
  an explicit review action. Saved progress is not described as a ready report.
- Confirmed logout discards the private document and saved selector; failed
  logout preserves the session and offers retry. A saved-call load timeout is
  surfaced rather than swallowed by an inner request catch.
- Profile disclosure uses native Tab navigation; Escape returns trigger focus.
- Existing provider, consent, policy, retention, ownership and quote contracts
  remain authoritative. No real recording or paid provider was used for QA.

## Executed validation

Windows, Node24, Next16.3.3 compiled build served at loopback3119, Chromium,
reduced-motion enabled. All `/v1/**` calls intercepted with synthetic fixtures;
external challenge script blocked and replaced by an explicitly synthetic widget.
The one-second silent PCM file is not a real call or a provider benchmark.

- `pnpm --filter @ac/sales-xray-web test`: **206 tests / 23 files passed**.
- `pnpm --filter @ac/sales-xray-web lint`: passed, zero warnings.
- `pnpm --filter @ac/sales-xray-web build`: passed including TypeScript.
- `node --test scripts/sales-xray-production-bridge.test.mjs`: **6 passed**.
- Independent final review: no blocking issues after fixes; reviewer separately
  reproduced 75 focused frontend tests and six bridge tests.
- `git diff --check`: passed.
- `scripts/verify-sales-xray-viewport.mjs`: **36 screen checks, four automatic
  upload-to-report transitions, four keyboard/shell checks passed**.

| Screen/state | 1440x900 | 1024x626 | 390x844 | 375x667 |
| --- | --- | --- | --- | --- |
| Entry | pass | pass | pass | pass |
| File selected | pass | pass | pass | pass |
| Verification visible | pass | pass | pass | pass |
| Upload in flight | pass | pass | pass | pass |
| Transcript C2 | pass | pass | pass | pass |
| Conversation C4 | pass | pass | pass | pass |
| Report C5 | pass | pass | pass | pass |
| Paused, saved work | pass | pass | pass | pass |
| Signed-out calls library | pass | pass | pass | pass |

Each screen assertion covers full document width/height, main panel height and
primary action visibility where applicable. Real state updates from synthetic
upload through C2/C4/C5 to the Overview tab were exercised without navigation,
overflow or page errors. Profile Enter/Tab/Escape and focus return passed at all
four sizes; desktop collapse/expand retained full viewport fit.

Machine results: [results.json](sales-xray-viewport-20260916/results.json).
Inspected screenshots: [entry](sales-xray-viewport-20260916/entry-1440x900.png),
[C4 desktop](sales-xray-viewport-20260916/C4-1440x900.png),
[small-phone paused](sales-xray-viewport-20260916/held-375x667.png),
[small-phone verification](sales-xray-viewport-20260916/verification-375x667.png).
All 36 screenshots are reproducible under `.tmp/sales-xray-ui-qa`.

## Reproduction

Build the app, serve the compiled output on a loopback port, then run:

```powershell
$env:SALES_XRAY_QA_ORIGIN='http://127.0.0.1:3119'
$env:SALES_XRAY_QA_STATES='entry,selected,verification,uploading,C2,C4,C5,held,calls'
node scripts/verify-sales-xray-viewport.mjs
```

## Boundaries and remaining slices

This evidence does not assert native phone testing, production latency, live
Turnstile completion, real-provider quality, or a deployed UI release. Root
release coordination must integrate this exact slice, run the release gates,
and verify the live guest/learner journeys before a production claim.

Long reports, expanded privacy details, browser text zoom and error content
retain accessible internal overflow instead of being clipped. Full report
Overview/Moments/skills/plan, mobile carousel/sheets, media availability,
AudioAtlas evidence, coach references and Admin node/settings/jobs work are
separate unfinished slices. DOCX/PDF redesign remains paused.

The requested additional image-model references are a separate design handoff;
actual generated images must not be described as implementation evidence or
substituted for the existing approved mockups. No image-generation result is
required by this already-understood repair's runtime or shipped bundle.
