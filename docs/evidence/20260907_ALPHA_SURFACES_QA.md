# Alpha Discover/Learning local fixture QA — 2026-09-07

## Scope and reproduction

This is **synthetic API-fixture evidence against a local development UI**, not live learner data, staging verification, production readiness, or performance proof. The visible development environment badge describes the local shell; it does not change this evidence classification.

```powershell
uv run python scripts/qa_alpha_surfaces.py --help
uv run python scripts/qa_alpha_surfaces.py --base-url http://learner.localhost:3100 --timeout-ms 15000 --output docs/evidence/screenshots/alpha-foundation-2026-09-07
uv run ruff check scripts/qa_alpha_surfaces.py
uv run ruff format --check scripts/qa_alpha_surfaces.py
```

The script uses a new headless Chrome process and isolated context per case, with no user profile, cookies, or imported storage. Service workers are blocked. All `/v1/` reads are locally fulfilled from narrowly defined synthetic fixtures; unknown API reads return a fixture-only 404. All non-read requests and off-origin non-fixture resources are blocked. It never starts/restarts servers or invokes enrollment, completion, sign-out, or other mutation controls. The learner origin is required and restricted to loopback/`.localhost`; no port is hardcoded.

The fixture contains one synthetic enrolled course and a synthetic person (`Learner QA`), with metadata-only progress for layout. It does not establish course authority, access eligibility, content completeness, or canonical progress. Neither fixture route renders a raster portrait; the instructor assets are not visually verified by this page matrix.

Every run receives a new timestamp directory. September 5 evidence and intermediate September 7 runs are preserved.

## Final run

Final verification: [run-20260907T122356Z/results.json](screenshots/alpha-foundation-2026-09-07/run-20260907T122356Z/results.json), Chrome 152.0.7977.82. **24/24 cases passed; zero assertion failures, horizontal overflow, page/console errors, unknown API reads, blocked write attempts, or external resource attempts.** The run produced 32 PNGs totaling 3,615,063 bytes.

The matrix covers `/discover` and `/learning`, light and dark, at 1440×900, 390×844, 320×844, 768×900, 1024×900, and 1920×1080 (24 cases). It records expanded and actually collapsed desktop screenshots, mobile screenshots, search/More dialogs, and 320 px layout screenshots. The other intermediate widths receive measured layout checks.

Assertions cover horizontal overflow, current-page breadcrumbs, mobile accessible identity and unclipped text, identity/action separation, 44 px header action targets, real sidebar hover then unforced click, command-palette filtering and keyboard focus trapping/restoration, mobile More trapping/restoration and cleared inert state, and desktop profile-name/More text contrast. Measured text colors include element/ancestor opacity; the JSON records the solid-color measurement assumptions and compositing layers.

Reduced-motion hover checks exercise each of `.ac-program-card` and `.learning-course-card` in both themes under OS reduce + system preference, OS no-preference + explicit reduced preference, and `data-reduced-motion=true`. Each must compute `transform: none`.

All 12 reduced-motion combinations, 8 search/filter/focus cases, 4 mobile More/focus cases, and 4 actual desktop collapses passed. Ruff lint/format checks and CLI help passed; a nonlocal origin was rejected before browser launch.

Representative final screenshots (visually inspected):

- [Dark desktop Discover, expanded](screenshots/alpha-foundation-2026-09-07/run-20260907T122356Z/fixture-discover-dark-1440x900-expanded.png)
- [320 px Discover, academy identity and search](screenshots/alpha-foundation-2026-09-07/run-20260907T122356Z/fixture-discover-light-320x844-layout.png)
- [Dark mobile More with semantic Sign out](screenshots/alpha-foundation-2026-09-07/run-20260907T122356Z/fixture-discover-dark-390x844-more.png)

Visual review also covered all 12 final primary route/theme/layout screenshots: each route in each theme at desktop expanded, desktop collapsed, and 390 px mobile. No unresolved important layout defect was found within this narrow fixture scope.

## Findings and supersession

- Mobile search was genuinely hidden by the old ≤1023 px CSS selector. Root restored a 44 px mobile search action. The subsequent `run-20260907T121856Z` verified search open/filter, eight Tab steps confined to the palette, Escape, and trigger-focus restoration in both themes/routes; 320 px identity and actions remained separate with no clipping or overflow.
- Desktop account-name text in dark mode was `#102349` over `#0a1420`, approximately **1.20:1 before opacity / 1.16:1 including the button's 0.85 opacity**, and was visually almost unreadable. An override-only attempt did not win the cascade (`run-20260907T122123Z` retained two failures). Root then replaced the hardcoded source declarations. The final color is `#edf2fb`, with effective foreground RGB (202.95, 208.7, 218.15) at 0.85 opacity over `#0a1420`: **12.03:1**.
- Dark More originally retained a white/light surface (readable but inconsistent with dark appearance). Root changed its surface, text, border, close control, muted text and danger color to semantic tokens. The final run verifies navigation at **14.50:1** and distinct semantic Sign out at **9.73:1** on `#142036`; the danger text is `#ffb4c0`, normal text `#edf2fb`, both at opacity 1. Sign out was never activated.
- The initial collapse failure was a test-setup issue: the rail intentionally exposes its control on hover/focus. Normal pointer entry followed by an unforced click reduces the rail from 280 px to 76 px. No production collapse fix was needed. The initial search result expectation was corrected from `Settings` to the observed `Settings & Appearance`.

## Visual observations and limits

The 320 px mobile academy identity uses the supplied 24×24 SVG within a 32×32 container; its two name lines fit without clipping. The inspected course surfaces retain clear heading/card hierarchy, and the one-course fixture leaves expected unused desktop space. The repeated course title in Discover's cover and body is a content-density choice, not a broken layout.

The local Next developer badge can overlap the bottom-left platform/footer or Home navigation in screenshots. This is development-tool chrome, not evidence of a production overlay defect. Full-page mobile screenshots capture a fixed bottom bar at the capture viewport's position; use viewport screenshots and interaction/layout results to judge fixed navigation.

This pass is not a full accessibility audit, device-browser compatibility certification, content audit, or a timing/Web Vitals measurement. No admin UI, real user/session, external media playback, or production backend was exercised.
