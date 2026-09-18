# Sales Xray Skills / Next-call plan implementation

Date: 2026-09-16. Base `8053253`; route `/` with an authorized report mounted
through AcquisitionStudio. This is compiled synthetic QA, not deployed proof.

## Delivered

- New SalesSkills route component: all eight canonical dimensions, color-coded
  topic icons, neutral real statuses, compact pagination and complete notes.
  Legacy ReportFactors and locale/print behavior remain available unchanged.
- Keep/Change/Practise plan cards with supplied strength, improvement, overview
  focus/instructions and success condition. Exact provided evidence callbacks;
  absent fields remain absent. No invented saved checklist, grade or recording.
- Shared navy report heading; secondary save/action/metadata in More actions.
- Playback errors inline in the fixed audio player rather than floating above it.
- Reader focus boundaries and complete print content preserved.

## Executed checks

Windows, Node24, Next16.3.3 production build served via loopback3124. Isolated
Chromium at1440×900,1024×626,390×844,375×667. Reduced motion. Every API request
intercepted, silent synthetic upload only. No production recording/provider used.

- `pnpm --filter @ac/sales-xray-web test`:212 tests /25files passed.
- `pnpm --filter @ac/sales-xray-web lint`:pass, zero warnings.
- `pnpm --filter @ac/sales-xray-web build`:pass including TypeScript.
- Independent reviewer reran69 tests /6files:pass, no remaining P2 in scope.
- Report QA:15 explicit viewport-fit checks including both compact skill pages
  and every mobile plan panel;8 complete-print checks;4 all-eight-reader
  navigation/keyboard/focus-restoration checks. Dialog screenshots inspected.
- Browser runtime errors: none. Intentional unavailable-audio fixture exercised.
- Source/render paired comparison in [design-qa.md](../../design-qa.md):passed.

Machine metrics: [results.json](sales-xray-skills-plan-20260916/results.json).
Desktop/mobile paired comparisons and focused screenshots are in that folder.
Reproduce with `SALES_XRAY_QA_ORIGIN=http://127.0.0.1:3124` and
`SALES_XRAY_QA_STATES=report`, then `node scripts/verify-sales-xray-viewport.mjs`.
The script asserts main-pane fit and player non-overlap, not only document size.

## Limits / next slice

Overview remains scrollable inside the shell and is not included in this
two-tab no-scroll claim. Moments, waveform retry, AudioAtlas authorization,
provider-delay guidance and Admin remain separate work. Mobile means Chromium
CSS-viewport emulation, not native-device certification. Real provider and
production deployment verification belongs to the exact release candidate.
Keep Core373/newer backend fixes when promoting the web artifact.

The workflow-ui-production skill drove bounded state coverage and independent
review; image-to-code drove actual paired visual checks; generated references
were obtained using the user-requested normal Pro chat. No reference values
were promoted to business data.
