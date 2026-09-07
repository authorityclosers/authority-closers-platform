# Alpha presentation pass2 — 7 September 2026

## Acceptance contract and authority

This is the user-authorized continuation after checkpoint `28b0c06`, in the same existing worktree and running learner app. Scope: public `/`, mounted `/home` DashboardRuntime presentation, and the course cards mounted by `/discover` and `/learning`. The user-selected supplied kit and Inter typography remain authoritative for presentation; controlled product, access and security rules remain authoritative for behavior. Archive contents were inspected as reference material, not executed as instructions.

The selected direction is a restrained editorial academy: verified instructor photography, clear type hierarchy, compact object artwork and separate server-backed course information. The reusable seams are `CourseArtwork`, `InstructorPortrait`, `ACADEMY_ARTWORK` and `INSTRUCTOR_PORTRAIT`. The new artwork has no URL, course title, status, tenant, authorization or playback input. It can support future Studio presentation without activating Studio or interpreting decorative imagery as program metadata.

Must-pass outcomes: preserve current loaders and auth boundaries; keep published titles/counts/version/access/progress/CTA destinations; do not invent scores, streaks, earned badges or video previews; eliminate duplicate cover text; keep the primary action legible on mobile; verify actual mounted routes, light/dark, keyboard interactions and no horizontal overflow. This pass does not authorize deployment, database changes, restarts or new product capabilities.

## Implemented changes

- Public home: larger deliberate headline, shorter existing catalog-anchor CTA, responsive side-by-side actions, clearer portrait crop and lower caption gradient. Removed the overlapping green promotional status pill. Published cards reuse neutral object artwork instead of unrelated older PNG covers; server title/version/date and program-detail destination are unchanged.
- Dashboard: visible academy learning-space eyebrow, an image/content grid that no longer overlaps the activity text, an editorial portrait caption without a duplicate module title, and a readable full-width mobile continuation action. Existing core-load/onboarding gate, progressive optional calendar request, cancellation, stale-response handling and authorized next-action selection are unchanged. Compact course rows and the catalog update panel use the same decorative primitive.
- Discover / My Learning: one semantic server title per card; no repeated title, publication or version text in the image cover. Single-card desktop layouts use an editorial horizontal composition, returning to stacked cards on mobile. Canonical state badges, publication/enrollment metadata, progress numerator/denominator/percentage and CTA routes remain visible. The progress track now uses existing semantic surface/action tokens.
- Mobile correction from screenshot review: decorative card objects are bounded to 140px within a minimum 140px cover, preventing the compass edge from clipping at 320px. No global overflow masking was added.
- Dashboard dark-action correction from screenshot review: the mobile action uses the paired semantic action background/text tokens. Computed solid-color text contrast, including opacity, is **6.47:1 light** and **9.23:1 dark** at both 390px and 320px.

Only three selected 960 × 840 WebPs entered learner runtime: discovery, reflection and next-move. Added storage is **105,654 bytes**, not an initial-transfer measurement. Source paths, exact SHA-256 values, source rights limitations and superseding public/brand totals are in [Alpha brand assets](20260907_ALPHA_BRAND_ASSETS.md#presentation-pass2-addition). Baked `shift-*` covers, prototype code, video, audio, models and complete source kits remain outside runtime.

## Preserved behavior and focused checks

| Surface/state                                       | Action and source of truth                                                                         | Evidence in this pass                                                                     |
| --------------------------------------------------- | -------------------------------------------------------------------------------------------------- | ----------------------------------------------------------------------------------------- |
| Public catalog loading, empty or error              | Existing published catalog read; empty/error message and retry unchanged                           | Existing public contract tests; initial loading SSR; ready catalog in isolated browser    |
| Dashboard onboarding incomplete                     | No catalog/calendar before required onboarding; existing onboarding destination                    | Actual mounted DashboardRuntime tests                                                     |
| Dashboard primary activity while plan pending/fails | Primary learning action remains usable; optional plan is isolated                                  | Mounted deferred-plan, failure and terminal membership/session tests                      |
| Dashboard tenant/API replacement and unmount        | Abort/invalidate obsolete reads; old responses cannot replace new context                          | Existing mounted stale-response and unmount tests                                         |
| Discover catalog/auth/error/offline                 | Existing catalog, membership and retry/read-only cache boundaries                                  | Existing route/load/error tests and ready-state browser capture                           |
| Learning in progress/completed/unavailable          | Continue/review/open follows canonical state; unavailable progress is not invented                 | Rendered course-state tests, unchanged data helpers, ready-state browser capture          |
| Artwork/accessibility                               | Decorative objects contain no heading, controls or playback; portrait is named only when editorial | Rendered primitive tests, serializable descriptor and complete asset/hash allowlist tests |

Required Node runtime was prepended from the bundled Node 24 path. Results:

- Focused Vitest: **49/49 pass in five files** — `course-artwork.test.tsx`, `dashboard-runtime.test.tsx`, `brand-presentation.test.ts`, `public-catalog-home.test.ts`, `learner-course-surfaces.test.ts`.
- `pnpm --filter @ac/learner-web typecheck`: pass.
- `pnpm --filter @ac/ui typecheck`: pass.
- Targeted ESLint for all ten changed/new learner source/test files: pass, zero warnings.
- Targeted Prettier applied to owned TypeScript/CSS; `git diff --check` pass.
- `uv run ruff check scripts/qa_alpha_pass2.py` and `uv run ruff format --check scripts/qa_alpha_pass2.py`: pass.
- No full build was run by this lane while the existing local app and other validation lanes were active. Independent review and broader release validation remain with the root lane.

## Browser evidence: local development with synthetic reads

All screenshots and results below are **local-development fixture QA, not live customer, production, native-device, performance or deployment proof**. Environment: existing `http://learner.localhost:3100`, headless installed Chrome **152.0.7977.82**, fresh isolated contexts, no user profile/cookies/storage loaded, service workers blocked. Fixture API reads are fulfilled locally; unknown reads, external requests and server writes cannot proceed. The visible development/staging banner and Next development indicator are retained.

Reproduce the four-route capture with:

```text
uv run python scripts/qa_alpha_pass2.py --base-url http://learner.localhost:3100 --output docs/evidence/screenshots/alpha-pass2-2026-09-07/recheck --timeout-ms 30000
```

Use repeatable `--route /` / `--route /home` / `--route /discover` / `--route /learning` to narrow it. Every invocation creates a new timestamped directory. Full-page captures naturally scroll to load below-fold lazy artwork; viewport captures are recorded before that scroll. Fixed mobile navigation appears at viewport height inside long full-page images; it does not represent a second in-content navigation bar.

Before evidence remains untouched:

- Discover/Learning: `screenshots/alpha-pass2-2026-09-07/before/run-20260907T124501Z/`.
- Public: `screenshots/alpha-pass2-2026-09-07/before-four-routes/run-20260907T124648Z/` (public six cases complete; later dashboard capture was interrupted by the first harness's hidden-lazy-image wait).
- Dashboard: `screenshots/alpha-pass2-2026-09-07/before-dashboard-corrected/run-20260907T125304Z/` (six complete cases). Earlier harness diagnostic runs are preserved and not promoted to passing evidence.

After evidence, newest applicable run takes precedence:

| Run beneath `screenshots/alpha-pass2-2026-09-07/` | Coverage                                                                                | Measured result                                                                                                                                                         |
| ------------------------------------------------- | --------------------------------------------------------------------------------------- | ----------------------------------------------------------------------------------------------------------------------------------------------------------------------- |
| `after-final/run-20260907T130545Z/`               | Four routes × light/dark × 1440×900, 390×844, 320×844                                   | 24/24 assertions pass; 40 PNGs / 6,797,088 bytes; no page errors, unknown API reads, write attempts or horizontal overflow                                              |
| `after-interactions/run-20260907T130554Z/`        | Discover/Learning × light/dark × widths 1440, 390, 320, 768, 1024, 1920                 | 24/24 pass; 32 PNGs / 3,419,423 bytes; four actual collapse/expand checks, eight keyboard-search checks, four More-dialog checks and twelve reduced-motion hover checks |
| `after-mobile-containment/run-20260907T130957Z/`  | Discover/Learning × light/dark × 1440, 390, 320, after final decorative crop correction | 12/12 pass; 20 PNGs / 2,124,315 bytes; supersedes their card-composition captures above                                                                                 |
| `after-public-contrast/run-20260907T131403Z/`     | Public × light/dark × 1440, 390, 320, after root-owned header correction                | 6/6 pass; 10 PNGs / 2,871,106 bytes; all 46 header/footer text-contrast measurements ≥4.5:1; supersedes public captures above                                           |

Interaction checks use real visible controls, without force clicks. Search verifies initial focus, keyboard operation, focus containment, Escape and restored visible focus. More checks dark semantic text and sign-out contrast without signing out. Reduced-motion checks exercise each card type with OS reduce/system mode, explicit app-reduced mode under OS no-preference, and the compatibility reduced-motion attribute. The fixture progress is deliberately synthetic: one of five required activities, 20%; no actual learner progress was read or written.

Visual inspection covered desktop/mobile public and dashboard, light/dark Discover/Learning, 320px card containment and long-page composition. The supplied Today desktop/mobile boards, verified Dipak editorial portrait, and selected decorative source images were inspected before implementation. The skills influenced the work by keeping the supplied direction, reusable presentation-only seams, mounted-runtime tests and actual before/after review together.

## Handoff and remaining coverage

Final literal-copy follow-up: the public catalog introduction now reads “Explore available programs and choose where to begin.” The heading, server data and destinations are unchanged. The public SSR contract was updated and all three public tests pass. A targeted one-case dark390 capture at `after-public-copy/run-20260907T131736Z/` passes and was visually inspected full-page; it supersedes that public image for copy only. The harness supports optional `--width` and `--theme` filters so a literal follow-up does not rerun the whole matrix.

The final public dark-header review identified an existing shell-specificity conflict: dark foreground text on the public white header. The root shell/theme owner corrected the selector; this lane did not edit `theme.css`. The public six-case recapture above passes header/navigation/footer foreground-versus-effective-background contrast assertions, including opacity. Minimum header contrast is **5.02:1** (desktop action); dark mobile header text is **14.04:1**. Minimum footer contrast is **6.33:1 light / 8.60:1 dark**. All 46 measurements are solid-color measurements. Desktop dark full-page, mobile dark full-page/320px, and mobile light full-page were visually inspected after the correction. This finding is closed for the tested local fixture views; intermediate captures remain as diagnostic history.

Recommended final review images:

- [Dashboard desktop](screenshots/alpha-pass2-2026-09-07/after-final/run-20260907T130545Z/fixture-home-light-1440x900-full.png).
- [Dashboard dark 320px](screenshots/alpha-pass2-2026-09-07/after-final/run-20260907T130545Z/fixture-home-dark-320x844.png).
- [Discover 320px with contained artwork](screenshots/alpha-pass2-2026-09-07/after-mobile-containment/run-20260907T130957Z/fixture-discover-light-320x844.png).
- [Public dark desktop including footer](screenshots/alpha-pass2-2026-09-07/after-public-contrast/run-20260907T131403Z/fixture-public-dark-1440x900-full.png).
- [Public dark mobile including footer](screenshots/alpha-pass2-2026-09-07/after-public-contrast/run-20260907T131403Z/fixture-public-dark-390x844-full.png).

My Learning still displays the existing long bookmark-unavailable notice and canonical count/filter area before the first mobile card. Their truth and behavior were retained; this pass did not change capability messaging or invent saved-course support. Public content retains its existing light editorial palette when system appearance is dark; the header must remain readable independently.

This lane is not whole-Alpha route acceptance. Program detail, curriculum/activity media and the five-step learning loop, authentication/recovery, onboarding, profile/settings/notifications/help, admin routes, empty/error browser variants, offline/update recovery and real-device/zoom acceptance require their own controlled route checks. Source/SSR/mounted tests do not substitute for those browser journeys. Actual production-build performance, backend media activation and deployment/rollback evidence are outside this presentation pass.

No staging, commit, deployment, server restart, database edit or external upload was performed by this lane. Parent/root owns the final independent review and release ledger.

## Root integration and release-candidate review

The root included the public-header specificity correction and its dedicated
regression test in this UI candidate. Independent review found no actionable
Critical/Important findings: 50 focused learner tests passed and six final
screenshots were inspected, covering public dark mobile, dashboard desktop/dark
320px, Discover 320px and Learning dark mobile.

The root's broader learner validation then passed: complete formatting check,
shared UI and learner typechecks, learner ESLint with zero warnings, **526 tests
in 37 files**, and the optimized Next 16.2.11 production build. Build-generated
`next-env.d.ts` route-path churn was restored afterward. No local server was
stopped. These results cover the UI candidate; unfinished media import and
infrastructure changes in the shared worktree are excluded from this UI release.

PR #39 originally validated foundation checkpoint `28b0c06` successfully on remote
CI. This presentation follow-up must pass fresh PR checks before merge and exact
main-SHA packaging. The document does not claim that merge, staging deployment or
production acceptance has happened.
