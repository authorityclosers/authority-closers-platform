# Learner analytics and support-shell increment

Status: bounded implementation on `codex/gamification-analytics-ui`.

## Scope

This increment extends the approved learner shell with the next desktop/mobile
slice:

- the existing persistent sidebar collapse control now gives a transient,
  keyboard/screen-reader-readable confirmation;
- the header bell opens an honest notification popover and retains the route
  link while durable notification history is unavailable;
- the header account control remains a real profile/settings dropdown;
- a fixed help chatbox shell exposes the existing learner-support mail route
  without pretending that live chat is connected; and
- `/progress` presents a source-labelled learning-rhythm panel backed only by
  `GET /v1/learning/insights`.

The analytics panel shows descriptive event counts, freshness, and authored
insight text only when the read model reports retained signals. With no signal,
it renders an explicit “No signal yet” state. It does not derive a streak,
points, rank, badge, mastery, completion, payment, entitlement, or access
value, and it cannot mutate canonical learning state.

## Controlled references

- `docs/traceability/CONTROLLED_SOURCE_REGISTER.md` — source authority and
  exact controlled-document register.
- `docs/workflows/learner-product-v1/03-visual-exploration/selection.md` —
  accepted Direction A shell and bounded analytics/gamification exclusions.
- `docs/workflows/learner-product-v1/06-screen-family-v0.1-alpha/03-handoff/component-contract.md` —
  responsive shell, `InsightPanel`, state, and accessibility contracts.
- `docs/product/PLANNING_ANALYTICS_ROUTE_CONTRACT.md` and
  `docs/adr/0029-planning-analytics-proposal.md` — read-only analytics route,
  insufficient-signal semantics, freshness, and no schedule/score inference.

## Implementation evidence

- `apps/learner-web/app/components/site-shell.tsx` — header notification
  popover, help chatbox shell, toast region, focus restoration, and sidebar
  collapse feedback.
- `apps/learner-web/app/components/learner-insights.tsx` — reusable analytics
  read-model loader and responsive presentation states.
- `apps/learner-web/app/components/progress-runtime.tsx` — analytics panel is
  additive to canonical progress and is not used to calculate completion.
- `apps/learner-web/app/lib/learner-api.ts` — same-origin, no-store read for
  `/v1/learning/insights`.
- `apps/learner-web/app/lib/dev-api-proxy.ts` — exact allowlist support for
  the read-only insights route in the opt-in staging bridge; period values are
  constrained to the promoted planning-period enum.
- `apps/learner-web/app/learner-next-slice.css` — responsive and reduced-motion
  presentation styles.
- `apps/learner-web/app/lib/learner-insights.test.tsx` — source/disclosure,
  no-signal, route, and not-promoted fallback tests.
- `scripts/qa_learner_next_slice.py` — local-fixture Playwright smoke capture
  for desktop and mobile progress surfaces.
- `docs/evidence/screenshots/learner-next-slice-progress-desktop.png` and
  `docs/evidence/screenshots/learner-next-slice-progress-mobile-help.png` —
  browser captures showing the responsive analytics panel, notification toast,
  and help chatbox shell.

## Verification

- `pnpm --filter @ac/learner-web typecheck`
- `pnpm --filter @ac/learner-web lint`
- `pnpm --filter @ac/learner-web test`
- `python scripts/qa_learner_next_slice.py` (against a local production Next
  server with deterministic read-only fixtures)

## Backend gap

The current planning analytics projection emits a generic descriptive planning
signal and retained-event freshness, not a controlled streak/day-by-day
contract. The UI therefore does not show a numeric streak or derive one in the
browser. A future streak presentation requires an explicitly promoted,
consent/retention-gated non-canonical read-model field and corresponding QA;
this branch does not add analytics ingestion, provider wiring, scoring, or
canonical progress mutations.
