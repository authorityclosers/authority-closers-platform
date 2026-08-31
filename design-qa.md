# Learner core Clarity Grid design QA

## Source visual truth

Approved Drive exports are materialized at:

`C:\Users\Suyash\.codex\visualizations\2026\08\31\ac-v01-design-references`

Compared reference family:

- `SHELL-01-desktop-home.png` — 1487 × 1058 px
- `SHELL-02-mobile-home.png` — 941 × 1672 px
- `HOME-01-mobile-dashboard.png`
- `COURSE-01-desktop-detail.png`
- `COURSE-02-mobile-detail.png`
- `PLAYER-01-desktop-player.png`
- `ACT-02-desktop-reflection.png`
- `ACT-03-desktop-implementation.png`
- `REVIEW-01-mobile.png`

The approved direction is Clarity Grid: white surfaces, navy/ink structure, indigo actions, restrained borders, compact learning UI, desktop rail/top bar, and mobile bottom navigation. Controlled route/state contracts remain authoritative over mockup-only media, reviewer, certificate, metrics, and navigation claims.

The Drive-aligned auth, session-recovery, onboarding, learner-state, and admin
captures are indexed in
`docs/evidence/screenshots/v0.1-drive-aligned/README.md`. They use 1440 × 900
desktop and 390 × 844 mobile viewports and replace stitched full-page capture
as the current visual evidence method.

## Implementation evidence

- Desktop browser capture: `C:\Users\Suyash\.codex\visualizations\2026\08\31\ac-v01-design-references\implementation-learner-home-desktop.png`
  - CSS viewport: 1280 × 720 px
  - Browser screenshot: viewport/full-page capture at the same 1280 × 720 CSS viewport; no density normalization applied.
- Mobile browser capture: `C:\Users\Suyash\.codex\visualizations\2026\08\31\ac-v01-design-references\implementation-learner-home-mobile-offline.png`
  - CSS viewport: 390 × 844 px
  - Browser screenshot: full-page capture; no density normalization applied.
- Browser: Codex in-app browser, local Next learner runtime at `http://127.0.0.1:3100`
- States captured: desktop loading shell and mobile offline state
- Console errors checked: none
- Responsive check: `document.documentElement.scrollWidth === window.innerWidth` at 390 px; no horizontal overflow.
- Auth/session recovery: login, registration, and `/session-expired` were
  captured at desktop/mobile sizes with one form and no horizontal overflow.
- Onboarding: the API-backed loading state was captured at desktop/mobile
  sizes; no local fixture was used to manufacture a profile.

## Full-view comparison evidence

The desktop and mobile captures were opened after the corresponding reference images. The implementation now follows the reference composition for the shell: fixed desktop learner rail, top search/actions, compact bordered content surfaces, and mobile header/search/bottom navigation. The offline state is deliberately rendered as a clear state panel and does not invent course data.

The ready authenticated state could not be captured locally because the local browser has no learner session. The implementation therefore does not substitute a local fixture or claim that seeded Module 1 data rendered in-browser.

## Focused region comparison evidence

- Desktop shell/header: rail width, selected Home treatment, search field, action cluster, and content offset were checked against `SHELL-01-desktop-home.png`.
- Mobile shell/navigation: header, search field, content width, and fixed bottom navigation were checked against `SHELL-02-mobile-home.png` and `HOME-01-mobile-dashboard.png`.
- Course/activity ready-state regions were validated by static component tests and implementation review, but not browser-captured with a real authenticated API response.

## Findings

- [P1] Authenticated ready-state browser evidence is missing.
  Location: local browser verification for `/home`, `/learn/[programSlug]`, `/learn/[programSlug]/module/[moduleId]`, and `/activity/[activityId]`.
  Evidence: the local learner browser has no authenticated learner session; only loading/offline surfaces were rendered.
  Impact: a real session is required to verify server-authoritative enrollment, the seeded VIDEO → REFLECTION → IMPLEMENTATION_CHALLENGE → REVIEW → IMPROVE sequence, locked states, and mutation feedback in the rendered browser.
  Fix: run the same screenshots in an authenticated staging learner session after the learner OAuth callback/session issue is resolved. Do not replace this with client fixtures.

- [P2] Mockup content is intentionally not reproduced where controlled capability contracts do not support it.
  Location: learner home/course/player/review surfaces.
  Evidence: no fake course metrics, media, captions, reviewer feedback, certificates, or unsupported navigation were added; video uses a media-pending state.
  Impact: pixel content differs from sample mockups, but this prevents false production claims.
  Fix: only replace pending/unavailable states when approved media/provider/reviewer contracts and server responses exist.

## Verification gates

- Focused learner Clarity tests: passed — 4 tests.
- Learner API tests: passed — 9 tests.
- Learner lint: passed.
- Learner typecheck: passed.
- Prettier check: passed.
- Learner production build: passed.
- Full repository validation: passed locally; Docker-backed PostgreSQL rerun
  is recorded separately because the default local gate intentionally skips
  database integration tests when URLs are absent.
- Local responsive browser check: passed for shell/loading/offline states.
- Console error check: passed for captured states.

## Comparison history

1. Initial learner surface used the prior sparse editorial shell and did not match the approved Clarity Grid navigation or density.
2. Fixed by adding the scoped learner Clarity Grid layer, responsive desktop/mobile shell composition, server-truthful enrollment/account cards, server-driven activity rows, locked activity icon treatment, and media-pending activity state.
3. Post-fix browser capture confirmed no mobile overflow and no console errors.
4. Ready-state comparison remains blocked until an authenticated learner browser session is available.

## Final result

final result: blocked

Blocker: authenticated ready-state browser evidence is not available in the local environment. The code and focused gates pass; full learner journey visual acceptance is intentionally not claimed.
