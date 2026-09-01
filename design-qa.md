# Authority Closers v0.1 Alpha design QA

## Controlled visual target

The visual target is the approved Authority Closers Drive package, fetched by
exact Drive ID under the controlled-source manifest. The selected direction is
the Clarity Grid system: white/ink surfaces, indigo actions, restrained borders,
compact learning UI, responsive learner navigation, and a separate admin
foundation. Route, state, authorization, and release contracts remain
authoritative when a mockup depicts future or unimplemented breadth.

The source registration frame used for the current same-viewport comparison is
the controlled auth export (`1K9qpP-OTsgyuhJ3mtmZYDj2-7EFv_MJb`). Additional
ready-state comparisons are required from the controlled learner shell, course,
reflection, progress, and admin source families after the candidate is deployed.

## Candidate implementation evidence

- Candidate: current uncommitted `codex/g1-free-course-foundation` worktree.
- Local learner preview: port 3000, inspected only through the selected in-app
  Browser.
- Registration comparison viewport: 1487 × 1058 CSS pixels.
- Mobile inspection viewport: 390 × 844 CSS pixels.
- Combined source/implementation comparison:
  `docs/evidence/design-qa/v0.1-alpha-20260901/comparisons/auth-register-source-vs-implementation.png`.
- Local implementation captures:
  `docs/evidence/design-qa/v0.1-alpha-20260901/implementation/`.
- Curated pre-candidate staging audit:
  `docs/evidence/screenshots/v0.1-staging-live-audit-20260901/`.

Historical staging screenshot folders are local-only and are deliberately
excluded from release commits because some contain account-identifying data.

## Source plus implementation comparison

The registration implementation preserves the approved split-screen hierarchy,
single primary heading, dense but readable account form, Google alternative,
versioned consent, and clear sign-in continuation. The same implementation
collapses to one column at 390 × 844 without horizontal overflow and maintains
44 px interactive targets. Login and protected-session boundary states were
also inspected at the mobile viewport. Light/dark/system theming is global and
the dark preference persists across route transitions.

The source and implementation were captured at the same desktop viewport and
placed in one combined image before visual judgment. This is a directional
fidelity review, not a pixel-diff claim: copy and form contents intentionally
follow the controlled runtime contracts.

## Current findings

- [Resolved locally] Auth and onboarding use the Clarity Grid visual system and
  responsive mobile composition.
- [Resolved locally] Learner home, exact Free Course path, five-activity Module
  1 loop, reflection/workbook, progress, settings, and global theme surfaces are
  implemented against server-authoritative data or explicit unavailable states.
- [Resolved locally] Session-expired, loading, error, offline, conflict, and
  locked/unavailable states are represented without fabricating protected data.
- [Pending staging] Authenticated ready-state source comparisons for home,
  course, reflection, progress/settings, and admin must be captured from the
  immutable candidate release at desktop and mobile viewports.
- [Pending staging] Real Google registration/login, password verification and
  recovery delivery, PWA/offline behavior, and live responsive interaction must
  be re-proven on the candidate release.
- [Intentional v0.1 boundary] Real course media playback remains provider and
  content-source gated. Modules 2–4 remain topology/extension contracts; broad
  LMS, native apps, billing, SSO/SCIM, simulator, and call-review breadth is not
  claimed.

## Verification state

- Backend unit gate: 152 passed.
- Focused PostgreSQL gate: 18 passed.
- Full PostgreSQL-backed Python suite: 924 passed, 21 documented skips.
- Python typecheck and Ruff: passed.
- Learner/frontend full gates: pending final reviewer-fix integration.
- Immutable exact-SHA CI/package/deploy: pending.
- Current-release authenticated staging journey and design comparison: pending.

## Final result

final result: blocked pending immutable staging visual acceptance

The local candidate is materially closer to the approved visual and interaction
contract, but design acceptance is not complete until the exact candidate is
packaged, deployed, exercised with canonical learner data, and compared with the
approved source families at matched desktop and mobile states.
