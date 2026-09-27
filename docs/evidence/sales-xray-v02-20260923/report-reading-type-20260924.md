# Report reading typography, 2026-09-24

The local synthetic report fixture at `/review-fixture/report` uses the production `ReportExplorer`, `SalesSkills`, and `NextCallPlan` components with invented dialogue. The report now uses a self-hosted Source Sans 3 variable font, lighter headline weights, and a clearer size and line-height hierarchy for observations and next-call guidance. Report data, section navigation, source actions, and copy were not changed.

Browser review in the local development build covered the Sales skills and Next-call plan tabs at 1024 × 768 and 390 × 844. At 1024px, document scroll width was 1009px; at 390px, it was 375px. Both were within the viewport, with no horizontal overflow. Text in the card summaries and next-call guidance remained readable at phone width. The fixture is synthetic and does not validate a coaching result.

Checks: `vitest run` for the fixture, report explorer, sales skills, and next-call plan passed (4 files, 15 tests). Sales Xray and learner TypeScript checks passed.
