# Sales Xray report typography — local implementation evidence

Date: 2026-09-24. Scope: development-only `/review-fixture/report` plus the shared Sales Skills, Next-call Plan, report tabs, and notes dialog. The fixture uses invented dialogue; this change does not alter report data or analysis.

## Change

- Self-host the variable Plus Jakarta Sans face through the pinned `@fontsource-variable/plus-jakarta-sans` package. The OFL notice is retained at `apps/sales-xray-web/public/fonts/plus-jakarta-sans-OFL.txt`.
- Give the fixture introduction less visual weight and vertical space. Make report section titles, card headings, body observations, status labels, tabs, and dialog text follow one type family and a clearer size/weight scale.
- Keep observation and plan body copy at 15px in compact desktop and mobile layouts; improve text contrast without changing report wording.

## Verification

- Browser: local development bridge `http://salesxray.localhost:3016/review-fixture/report`, 1024×768 and 390×844. Confirmed `document.fonts.check('750 16px "Plus Jakarta Sans Variable"') === true`; the page and section headings resolve to that face. Both report tabs and the plan notes dialog rendered with the updated type. At 390px, document width was 375px, so there was no horizontal overflow.
- `pnpm --filter @ac/sales-xray-web exec vitest run app/review-fixture/report/synthetic-report-preview.test.tsx app/sales-skills.test.tsx app/next-call-plan.test.tsx`: 3 files, 9 tests passed.
- `pnpm --filter @ac/sales-xray-web typecheck`: passed.
- `git diff --check`: passed.

The development fixture still scrolls vertically at 1024×768 (891px document height on the Next-call Plan tab); its full report content and source interaction panel remain available. No production deployment was performed.
