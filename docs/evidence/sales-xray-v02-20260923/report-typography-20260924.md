# Sales Xray report typography pass — 2026-09-24

## Scope

- The synthetic report fixture and its shared Sales skills, Next-call plan, and report tab styles.
- Increased the reading size and moderated heading weights at compact desktop widths.
- Kept skill observations visible in two columns at 1024px; stacked skill cards at mobile widths so labels remain intact.
- No report data, scoring, navigation, or API behavior changed.

## Checks

- `pnpm --filter @ac/sales-xray-web typecheck` — passed.
- `pnpm --filter @ac/sales-xray-web exec vitest run app/review-fixture/report/synthetic-report-preview.test.tsx app/report-explorer.test.tsx app/report-moments.test.tsx` — 3 files, 21 tests passed.
- `git diff --check` — passed.
- Live synthetic report at `http://salesxray.localhost:3016/review-fixture/report`: reviewed both tabs at 1024×768, 390×844, and 1440×900. At 1024px, the Next-call card heading/body computed to 17px/14px and Sales skills to 16px/14px. Document width matched client width at 1024px (1009/1009) and mobile (375/375), so neither had horizontal overflow. The 1440×900 Sales skills view fit within the viewport.

The local runner reported a Node engine warning (repo expects Node 24; this shell used Node 22) while the typecheck and focused tests passed. This route is a synthetic visual fixture, not a validated coaching report.
