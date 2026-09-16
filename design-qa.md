## Profile, Settings, and click-first onboarding design QA

Final Direction B QA for the profile/settings and click-first onboarding route
family. The visual result, real browser workflow, responsive checks, and Node24
validation matrix pass. A fresh independent Luna/`xhigh` merge-gate review of
the corrected working tree passed with no P0, P1, or P2 findings.

## Selected sources

- .artifacts/ui-workstream/profile-settings-onboarding/03-visual-exploration/selected/PSO-DIR-B-settings-desktop.png — 1440 × 1024
- .artifacts/ui-workstream/profile-settings-onboarding/03-visual-exploration/selected/PSO-DIR-B-settings-mobile.png — 390 × 844
- .artifacts/ui-workstream/profile-settings-onboarding/03-visual-exploration/selected/PSO-DIR-B-onboarding-desktop.png — 1440 × 1024
- .artifacts/ui-workstream/profile-settings-onboarding/03-visual-exploration/selected/PSO-DIR-B-onboarding-mobile.png — 390 × 844

## Final implementation evidence

- .artifacts/design-qa/profile-settings-onboarding/settings-desktop-completed-final.png
- .artifacts/design-qa/profile-settings-onboarding/settings-mobile-completed-final.png
- .artifacts/design-qa/profile-settings-onboarding/onboarding-desktop-final-7.png
- .artifacts/design-qa/profile-settings-onboarding/onboarding-mobile-final-5.png
- .artifacts/design-qa/profile-settings-onboarding/settings-desktop-final.png
- .artifacts/design-qa/profile-settings-onboarding/settings-mobile-final.png
- .artifacts/design-qa/profile-settings-onboarding/onboarding-desktop-post-hardening.png
- .artifacts/design-qa/profile-settings-onboarding/onboarding-mobile-post-hardening.png

Combined comparisons:

- .artifacts/design-qa/profile-settings-onboarding/settings-desktop-comparison-passed.png
- .artifacts/design-qa/profile-settings-onboarding/settings-mobile-comparison-passed.png
- .artifacts/design-qa/profile-settings-onboarding/onboarding-desktop-comparison-passed.png
- .artifacts/design-qa/profile-settings-onboarding/onboarding-mobile-comparison-passed.png

Additional states:

- .artifacts/design-qa/profile-settings-onboarding/onboarding-desktop-loading-final.png
- .artifacts/design-qa/profile-settings-onboarding/onboarding-completion-focus-final.png

## States, viewports, and density

The captures cover an authenticated QA learner, Avery, with verified identity
and exact learner membership. Settings shows the complete profile with Sales,
“Close more consistently,” no situation, and 30 minutes. Onboarding was checked
across Context, Goal, optional Situation, Weekly time, Review, and Completion.
Both routes were checked at the exact 1440 × 1024 and 390 × 844 desktop/mobile
viewports; no horizontal overflow was present.

Settings mobile controls and policy links have hit targets of at least 44px.
Onboarding mobile actions have hit targets of at least 44px. The final desktop
Onboarding card measures approximately x504, y84, width 880, height 512.7,
against the selected source at approximately x499, y84, width 883, height 510.

## Real workflow QA

The QA workflow selected a goal, advanced to the optional situation, continued
without a situation, selected 30 minutes, reviewed, saved, and reached
completion. Completion exposed Return to settings, and Settings immediately
rendered the canonical saved values. Light/Dark/Light toggling worked and the
final theme returned to Light.

Fresh post-edit browser tabs had no application errors or warnings. The only
warning observed in older tabs was the dev-only Fast Refresh warning while
source files were actively changing.

## Findings corrected

- Neutral unresolved loading state with no guessed Step 1.
- Source-faithful bordered form and neutral ledger.
- Numbered/check step rail and connector.
- Secondary custom-goal affordance.
- Desktop and mobile density.
- return=settings allowlist.
- Completed-profile dirty recovery.
- 64-character contract.
- Unknown context rendering.
- Request generations.
- Dirty copy/download.
- Cleanup-pending honesty.
- Focus restoration and focus-visible completion.
- A true 44 × 44 mobile profile/settings target after a conflicting mobile
  min-width rule was discovered in browser QA.
- Programmatic Settings route-entry focus after Onboarding completion, with the
  non-interactive H1 focus outline suppressed through a correctly scoped CSS
  Module class while interactive focus treatment remains intact.
- Next route-transition scroll-behavior metadata, eliminating the development
  warning without removing smooth scrolling.
- Operation-owned onboarding and activity recovery envelopes, so post-server
  compare-and-clear cannot delete a newer cross-tab recovery record.
- Delayed activity recovery hydration that preserves input edited while the
  recovery read is pending.
- Person-, membership-, generation-, and unmount-scoped membership cleanup
  publication guards.
- Executable concurrency coverage for newer-record retention, delayed
  hydration, and stale cleanup suppression.

## Intentional deviations

Existing LearnerShell, compact mobile shell, live QA identity, and canonical
values take precedence over generated chrome and mock data. The implementation
does not expose fake avatar upload, notifications, deletion, purchases, paid
offers, or entitlement logic.

Automated validation on Node 24.19.0 and pnpm 11.19.0 passed: 168 learner tests,
TypeScript, zero-warning ESLint, repository formatting, production build, and
`git diff --check`. The final independent Luna/`xhigh` merge gate passed with
no P0, P1, or P2 findings. Its residual P3 notes are that mounted component
tests remain thinner than the production guard/storage interleaving tests and
that all supported localStorage writers must continue honoring the shared Web
Lock protocol.

final result: passed

---

# Premium learner shell, offline recovery, and staging preview

## Reference and implementation comparison

- Desktop source: `C:/Users/Suyash/AppData/Local/Temp/codex-clipboard-2c74aa09-8977-42f4-b7c7-932ebd9f2fee.png` (`1487 × 1058`).
- Mobile source: `C:/Users/Suyash/AppData/Local/Temp/codex-clipboard-a2aefe32-de7a-496f-b0f2-5e6898d0b2fc.png` (`853 × 1844`).
- Local desktop capture: `.artifacts/design-qa/final-candidate/local-discover-desktop-1440x1024.png`.
- Local mobile capture: `.artifacts/design-qa/final-candidate/local-discover-mobile-390x844.png`.
- Desktop comparisons: `.artifacts/design-qa/final-candidate/comparison-reference-primary-desktop.png` and `.artifacts/design-qa/final-candidate/comparison-reference-alternate-desktop.png`.
- Mobile comparison: `.artifacts/design-qa/final-candidate/comparison-reference-mobile.png`.

The final implementation must be rechecked on real application routes at exact
1440 × 1024 and 390 × 844 viewports. The intended desktop result
retains the selected 240-pixel navigation rail, centered utility search, calm
canvas, two-column lead row, three-column supporting row, and full-width banner
rhythm. Mobile retains the monogram header, compact actions, stacked content,
and five-item fixed navigation. The mobile document width equals the 390-pixel
viewport with no horizontal overflow.

## Findings corrected

- Reconciled Antigravity's `ac-*` dashboard stylesheet with the component's
  actual class vocabulary; the generated CSS was otherwise unused.
- Closed an interrupted CSS block that caused the browser to discard the new
  dashboard rules.
- Added the missing desktop/mobile visibility utilities and a 390-pixel
  side-by-side Continue composition.
- Removed fabricated developer identity, enrollment, progress, schedule,
  coaching, analytics, launch, and notification data.
- Replaced implied media playback with a neutral learning-path treatment until
  an approved media provider and asset exist.
- Removed the unconditional unread badge and restored a neutral identity
  fallback.
- Added abort propagation, URL-safe dynamic segments, route-state previews,
  disclosure semantics, collapsed-state semantics, and disabled offline/locked
  activity rows.
- Removed a hidden full-access staging proxy branch; local remote-data preview
  remains restricted to credential-stripped, anonymous, allowlisted catalog
  GETs even if an undeclared override is present.

## Intentional controlled deviations

The reference is a visual composition target, not canonical product state.
Today's timed plan, calendar/coaching sessions, weekly time analytics, multiple
enrolled-course aggregation, notify-me, bespoke thumbnails, and playback are
not rendered as facts because the controlled first-slice API/data contracts do
not provide them. Authenticated staging—not local credential forwarding—is the
required proof for real learner data.

## Validation

The frozen local candidate passed 248 learner tests, zero-warning ESLint,
TypeScript, formatting, service-worker syntax, and the optimized production
build. The shared mark also passed 71 admin tests, zero-warning ESLint,
TypeScript, and the admin production build. Exact-SHA CI/package, staging
identity, and authenticated current-release smoke remain separate open release
gates; this local visual result does not claim them.

final result: passed

---

# Auth, onboarding, and session recovery design QA

Result: **PASSED** — no open P0, P1, or P2 visual defects in the implemented frontend scope.

## Visual target

- Desktop: `.artifacts/ui-workstream/auth-onboarding-desktop/03-visual-exploration/generated/AOD-DIR-B-studio-ledger-1440x1024.png`
- Mobile: `.artifacts/ui-workstream/auth-onboarding-mobile/03-visual-exploration/generated/direction-continuity-canvas.png`
- Contract corrections: `.artifacts/ui-workstream/auth-onboarding-paired-selection/independent-paired-selection.md`

The generated boards were treated as composition references, not literal product truth. The implementation removes generated help/marketing navigation, optional WhatsApp, last-name, remember-me, broad persistence claims, and incorrect expiry copy.

## Combined visual comparisons

- `.artifacts/ui-workstream/auth-onboarding-implementation/comparison-desktop-source-vs-implementation.png`
- `.artifacts/ui-workstream/auth-onboarding-implementation/comparison-mobile-source-vs-implementation.png`

The shared implementation retains the selected compact masthead, task ledger, focused form column, calm surface hierarchy, bounded states, and one-task mobile continuity. It intentionally uses the active AC theme tokens instead of copying the generated board palette.

## Browser checks

Checked locally in the Codex in-app browser against `http://localhost:3000`:

- Desktop viewport: 1440 × 1024.
- Mobile portrait: 320 × 568, 390 × 844, and 430 × 932.
- Mobile landscape: 844 × 390.
- Routes: `/login`, `/register`, `/forgot-password`, `/verify-email`, `/session-expired`, `/auth/callback?result=registration_required`, and `/onboarding` recovery.
- Every checked route had one `h1` and no horizontal overflow.
- Interactive controls use at least a 44-pixel target in the implemented shell; the 20-pixel consent control is contained by its full clickable label.

## Findings corrected during QA

1. Mobile grid stretching created large gaps between the task heading and form. The mobile workspace now has explicit `auto / 1fr` rows and top-aligned form content.
2. Registration and sign-in repeated their page heading inside the form. Form headings now describe the task detail instead.
3. Brand, footer policy, and compact account links did not all expose 44-pixel targets. Their target boxes were expanded.
4. Initial onboarding load failure incorrectly mentioned a failed recovery-copy write. It now reports only the profile-load failure and offers a retry.
5. Verification resend fields shrank inside the result grid. Result forms now use the full content width.

## Accessibility and motion

- Semantic forms, fieldsets, labels, autocomplete values, one page heading, and current-step semantics are present.
- Error summaries receive programmatic focus after failed login, registration, recovery, reset, and onboarding saves.
- Password reveal controls expose `aria-label` and `aria-pressed`.
- Step-heading focus moves after onboarding transitions.
- Focus outlines use the existing theme focus token.
- Reduced-motion preferences collapse transitions and animations.
- Safe-area padding is applied to mobile masthead and footer.

## Evidence limitation

The local frontend-only browser run had no authenticated API session, so the onboarding happy-path form was verified through component implementation and automated tests while the browser captured its honest load-recovery state. The original comparison capture used the dark system theme. After the integrated theme patch, a fresh in-app browser tab verified that sign-in now opens light by default; explicit dark and system preferences remain covered by tests. No authenticated onboarding success state was manufactured.

---

# Learning-loop activity design QA

## Comparison target and exact captures

- Selected desktop direction: `.artifacts/ui-workstream/learning-loop/selected-corrected/momentum-workshop-corrected-desktop-v2.png` (`1487 × 1058`).
- Selected mobile direction: `.artifacts/ui-workstream/learning-loop/selected-corrected/momentum-workshop-corrected-mobile-v2.png` (`853 × 1844`, normalized to `426 × 922`).
- Production desktop: `.artifacts/ui-workstream/learning-loop/implementation-qa/activity-desktop-1440x1024.png` (`1425 × 1013` browser content captured from a `1440 × 1024` viewport).
- Production mobile light: `.artifacts/ui-workstream/learning-loop/implementation-qa/activity-mobile-normalized-426x922.png` (`426 × 922`).
- Production mobile dark: `.artifacts/ui-workstream/learning-loop/implementation-qa/activity-mobile-dark-426x922.png` (`426 × 922`).
- State: authenticated learner, Module 1, reflection 2 of 5, one completed predecessor, three server-locked successors, empty editable draft.

## Combined visual evidence

- Desktop: `.artifacts/ui-workstream/learning-loop/implementation-qa/comparison-desktop.png`.
- Mobile: `.artifacts/ui-workstream/learning-loop/implementation-qa/comparison-mobile-normalized.png`.

The exact production shell and activity component were rendered with a server-authoritative fixture, then placed beside the normalized selected direction. Desktop retains the wide task canvas and module rail. Mobile retains the single-task hierarchy, labelled response, visible path disclosure, and Save/Submit actions above the fixed navigation. There is no horizontal overflow or fixed-navigation overlap.

## Independent review findings corrected

1. Authoritative identity: activity detail now returns the enrollment-owned `program_id`; dependent learning requests are scoped by exact `program_id`, `program_version_id`, and `enrollment_id`. Ambiguous active version enrollments fail closed instead of selecting a path or raising `MultipleResultsFound`.
2. Route identity: activity state reloads when the dynamic activity ID changes, and the activity workspace is keyed by authoritative activity identity.
3. Mutation reconciliation: a successful save/submission remains a success even if dependent path refresh fails. Draft saves do not request the full path. Evidence reconciliation uses a latest-generation guard so an initial or older response cannot overwrite a newer server snapshot.
4. Stale path safety: module/path UI is derived only from a `ready` learning snapshot; mismatch, access denial, unavailable, retry, and refresh failures clear or hide the previous path.
5. Recovery safety: blocked `localStorage` access is treated as unavailable. Before-unload, internal-link, Navigation API, and browser-history guards protect dirty responses when no recovery copy exists.
6. Error boundaries: session expiry offers sign-in, forbidden access offers learner support, 404 remains an unavailable path, and only retryable failures offer Retry.
7. Accessibility: all skip-link targets are focusable; mobile bottom navigation follows main content in DOM order; inactive dark mobile navigation now uses a token with approximately `9.5:1` contrast; the module disclosure has a visible Lucide chevron; labels and 44-pixel targets remain present.
8. Visual density: desktop and exact `426 × 922` mobile captures keep Back, Save reflection, and Submit evidence in the first task viewport. Light and dark captures remain readable.

## Verification evidence

- Learner web: 118 tests passed; ESLint passed with zero warnings; TypeScript passed; production build passed.
- Python learning HTTP: 12 focused unit tests passed; Ruff check passed. A PostgreSQL exact-scope regression assertion is present but remains environment-gated when the local PostgreSQL test URL is absent.
- Repository formatting and `git diff --check` passed.
- Local host Node is `22.17.0` while the repository requires Node 24; the sequential production build passed with a bounded heap, and CI remains authoritative on Node 24.
- Three independent Luna/`xhigh` reviews covered correctness/security, accessibility/responsive fidelity, and test/performance/release readiness. Their final verdicts contain no open P0, P1, or P2 findings.

## Intentional product boundaries

- Published server prompt, canonical activity order, real lock reasons, and allowed actions override generated mock copy.
- Save and evidence submission remain separate authoritative actions.
- Reflection is explicitly not an evaluation. No AI score, invented reward, or client-manufactured progress state is introduced.

## Follow-up polish

- P3: reconsider a full-width primary Save treatment at the smallest breakpoint only if task evidence supports it; the current dual-action row preserves two distinct server operations.

final result: passed

---

# Learner sidebar and command-palette design QA

## Reference and implementation evidence

The supplied Gemini and ChatGPT sidebar images were inspected as ephemeral conversation attachments. They are not committed repository artifacts, so their temporary operating-system paths are deliberately not recorded as durable evidence. The implementation follows their dark, text-forward hierarchy, compact icon rail, restrained active state, and anchored account footer while retaining the existing light learning canvas and AC product tokens. It does not copy unrelated chat recents, projects, or fabricated counters into the LMS.

Before the correction pass, the authenticated localhost shell was observed in the Codex in-app browser at desktop (`1425 × 891`) and mobile (`414 × 922`) viewports, including expanded sidebar, collapsed rail, command palette, `/home`, and `/progress`. Those observations were not saved as committed screenshots and therefore are not durable release evidence.

After the authorized clean Turbopack recovery, the correction pass was verified in the Codex in-app browser at desktop (`1280 × 720`) and mobile (`430 × 932`). Desktop checks covered the expanded `252px` rail, collapsed `64px` rail, matching header/main offsets, exact palette focus restoration, inert cleanup, and `Ctrl` + `K`. Mobile checks covered a persisted collapsed preference with zero hidden-rail offset, `/calendar` More current-state semantics, overlay ordering above help and bottom navigation, forward/reverse focus trapping, Escape cleanup, and exact More-button focus restoration. The in-app browser surface did not expose screenshot capture, so these are live DOM, accessibility-tree, and computed-layout observations rather than durable image evidence. Authenticated staging screenshots remain required before release.

## Findings corrected during QA

1. The initial identity treatment stacked controls and allowed the collapse action to overlap the wordmark. It is now one horizontal row: tenant mark, `Closers Academy`, `by Authority Closers`, and a far-edge collapse control.
2. The original collapsed state exposed cramped labels and unreliable hover layering. The rail is now icon-only with bounded tooltips, a clear active rail, and stable expansion behavior.
3. The redundant header context label was removed. The centered search remains, while notification and learner-profile controls use the quieter borderless shell treatment.
4. Sidebar search, header search, and `Ctrl`/`Cmd` + `K` now open one real command palette with filtering, arrow-key movement, Enter navigation, Escape dismissal, and route-backed results.
5. Escape initially restored focus to the header search even when the sidebar opened the palette. The invoking control is now captured dynamically, so focus returns to the exact sidebar, header, or shortcut origin.
6. Mobile retains the existing bottom navigation, safe-area behavior, and real destinations without inheriting the desktop rail.
7. Duplicate mobile More modal behavior was removed from the shell. `MobileMoreSheet` is now the single owner of Escape, focus trapping, inert background state, cleanup, and focus restoration.
8. The command palette now uses a stable hidden dialog title, traps forward and reverse Tab navigation, restores prior inert state, and returns focus to the exact invoking control.
9. A persisted collapsed preference no longer reserves a hidden 64-pixel rail at or below `1023px`.
10. `/calendar` now marks More as the current mobile destination.
11. The mobile More overlay is layered above the fixed help widget and bottom navigation.
12. The unused header title was removed, clearing zero-warning lint, and the unapproved handcrafted academy SVG was replaced with the approved shared `BrandMark`.
13. App-agnostic badge and tooltip primitives plus tenant-identity contracts now live in `@ac/ui`; learner routing, labels, sign-out, and business behavior remain in the learner adapter.
14. The desktop collapse transition could leave the rendered rail and content offsets at `252px` despite the collapsed state. The collapsed selector now resolves immediately to `64px`, while expanded-state motion remains intact.
15. Dot badges no longer place their screen-reader label inside an `aria-hidden` visual wrapper; the visual dot remains decorative and the label is exposed separately.
16. Command-palette focus remains in a real combobox whose `aria-controls`, `aria-expanded`, `aria-autocomplete`, and `aria-activedescendant` relationships now announce the selected listbox option as arrow-key navigation changes it.
17. Multi-tenant switching is not exposed unless the host supplies a real authorized selection handler; the no-op custom-event fallback was removed.

## Verification evidence

- Bundled Node `24.19.0` and pnpm `11.19.0` were used.
- `@ac/ui` TypeScript passed.
- Learner ESLint passed with zero warnings and learner TypeScript passed.
- Full learner suite: 31 files and 461 tests passed, including mounted DOM interaction coverage for both modal surfaces and combobox active-descendant updates.
- Focused sidebar suites: 35 tests passed.
- Scoped repository formatting and `git diff --check` passed.
- Live browser logs contained no application errors; only development-mode React/HMR information was present.

## Final assessment

No open P0, P1, or P2 local interaction defect remains in this sidebar slice. The tenant relationship is explicit: Closers Academy is the learner academy and Authority Closers is the tenant/operator; the reusable LMS itself remains unnamed. Local implementation QA passed; release sign-off remains blocked until authenticated staging supplies fresh durable captures.

final result: passed locally; release blocked pending authenticated staging visual evidence

---

# Approved learner shell specification — final local QA

## Source truth and implementation evidence

- Approved visual specification: `C:/Users/Suyash/.codex/visualizations/2026/09/04/01a06c32-45d7-7d80-baee-77e1a80a88f4/closers-academy-learner-shell-spec.png` (`1590 × 1840`).
- Vector companion: `C:/Users/Suyash/.codex/visualizations/2026/09/04/01a06c32-45d7-7d80-baee-77e1a80a88f4/closers-academy-learner-shell-spec.svg`.
- Supplied composition references: Gemini and ChatGPT sidebar screenshots attached to this Codex task.
- Live implementation: `http://learner.localhost:3000/home`, inspected in Codex's in-app browser at `1265 × 711` CSS pixels.
- Live authentication recovery: `http://learner.localhost:3000/login`, inspected in the same browser after the local staging bridge repair.

The Codex browser capture is retained inline with this task but does not expose a stable filesystem path. The approved board and live browser were therefore compared as a focused shell-region review: the board's light expanded, light collapsed, hover/focus, dark-theme, and mobile panels against the corresponding implementation states. The source is a multi-state specification board rather than a single route screenshot, so density normalization was limited to component geometry and CSS-pixel measurements; application content below the shell was not treated as a pixel-match target.

## Final comparison

- The light theme renders a light sidebar; the dark sidebar palette is limited to `html[data-theme="dark"]`.
- The expanded rail is `280px`, the collapsed rail is `76px`, and the header is aligned to `76px`.
- The tenant hierarchy is explicit: `Closers Academy` is the academy, `by Authority Closers` is the tenant attribution, and the LMS itself remains unnamed.
- The shared `BrandMark` and Lucide icons are used; no handcrafted SVG, CSS drawing, emoji, or substitute font was introduced.
- The collapse control is hidden at rest and overlays the brand region on sidebar hover or keyboard focus in both expanded and collapsed states.
- Collapsed navigation labels render through a body portal above the page rather than clipping behind the content layer.
- The header no longer repeats the active page label. Its centered search and quiet notification/profile actions remain, on a transparent, borderless shell surface.
- Desktop and mobile navigation preserve the existing real routes and responsive shell behavior.

## Interaction and runtime checks

- `Ctrl`/`Cmd` + `K` opens the functional command palette.
- Arrow navigation, Enter routing, Escape dismissal, and invoker-focus restoration are covered by the mounted component suites; Escape and exact focus restoration were also exercised in the live browser.
- Collapse and expand were exercised in the live browser.
- A focused collapsed navigation item displayed its tooltip over the content without clipping.
- The login page remained stable and showed the sign-in form after the bridge repair; the previous offline/reload flicker did not recur.
- Final browser console check returned no application warnings or errors.
- Learner proxy health returned HTTP `200` with `X-AC-Dev-Data-Mode: staging-public-catalog`.
- Admin bridge health returned HTTP `200`, `status: ok`, `transport: connected`.

## Comparison history and severity assessment

Iteration 1: the approved board and live implementation were compared after the Antigravity implementation and localhost bridge repair. No actionable P0, P1, or P2 visual or interaction defect remained, so no post-comparison visual correction was required. The unauthenticated home content is an honest local session state and was excluded from shell-fidelity scoring; authenticated staging content remains a release-environment check, not a local shell blocker.

Automated verification passed under the repository Node 24 runtime: 31 learner test files and 469 tests, TypeScript, zero-warning ESLint, production build across 25 routes, focused learner/admin proxy suites, seven local-bridge infrastructure tests, and `git diff --check`.

final result: passed

---

# Sales Xray Skills / Next-call plan — design QA

Date: 2026-09-16. Scope: this bounded report slice, not the complete report
redesign. Upload/processing retains the separately released `4c8cfe9` behavior.

## Source and rendered comparison

User visual truth: the ten supplied Sep16 00:13 report mockups. Selected
contract-faithful derivatives: `docs/design/sales-xray-20260916/skills-{desktop,mobile}-v1.png`
and `plan-{desktop,mobile}-v1.png`. They are genuine image-model outputs, not
implementation screenshots. They preserve the selected palette while retaining
all eight actual dimensions and excluding unsupported scores/checklists.

Compiled Next build, loopback3124, isolated Chromium, synthetic report, light
theme, reduced motion, deviceScaleFactor1. All API calls intercepted; no actual
call processing. Implementation captures: `.tmp/sales-xray-ui-qa/`.
Durable comparisons and details: `docs/evidence/sales-xray-skills-plan-20260916/`.

| Comparison evidence | Source pixels | Render pixels / CSS viewport | Normalization |
| --- | --- | --- | --- |
| comparison-skills-desktop.png | 1586×992 | 1440×900 | Source contained in1440×900; both displayed side by side |
| comparison-plan-desktop.png | 1586×992 | 1440×900 | Same |
| comparison-skills-mobile.png | 940×1672 | 375×667 | Source contained in375×667; both displayed side by side |
| comparison-plan-mobile.png | 940×1672 | 375×667 | Same |

The 36px comparison caption is outside both viewports. No device chrome was
introduced. The generated sources include illustrative copy, missing-audio
states and simplified shell; implementation uses the actual synthetic server
projection, shared guest shell, and a real unavailable-audio error. These data
and existing-shell differences are intentional, not a pixel-identical claim.
Focused checks used the full1024×626 captures and375×667 note sheets; text,
icons, card boundaries and fixed footers are readable at these capture sizes.

## Findings and fixes

- P2, fixed: compact desktop cards and short-phone plan evidence were covered
  by the fixed player. Earlier main scroll heights were689/663px inside564px
  at1024×626 and537/590px inside521px at375×667. Four skills now occupy one
  compact desktop row; short-phone cards reduce secondary preview copy, keep
  the full reader, and remove redundant spacing. Post-fix metrics below.
- P2, fixed: report metadata/sign-in content and an empty header consumed
  vertical space. A single navy report heading is shared across tabs; secondary
  actions and metadata are in More actions, preserving guest save access.
- P2, fixed: playback failures floated over report content. They now occupy the
  player's identity/status area; no report content is covered by a toast.
- P2, fixed in independent review: reaching a disabled Next button could leave
  focus outside the trap. Navigation now focuses the changed heading; Shift+Tab
  wraps to the last enabled control, including both boundaries.
- P2, fixed in independent review: compact screen clamps could survive print.
  Print now includes all eight skills, all three plan sections, and full notes.

## Required fidelity surfaces

- Typography: existing local sans-serif stack, bold navy heading, clear topic
  labels and moderate body hierarchy. Compact summaries may clamp; exact full
  text remains in the reader and print. No type reduced merely to fit a long
  report. Short mobile drops the optional main tagline.
- Spacing/layout:4×2 skills on roomy desktop, paginated four-card groups on
  compact screens, three plan columns or one selectable mobile panel. Thin
  borders,14–15px radii and consistent gaps. All tested controls fit above the
  real fixed player; no page or main-pane scrolling in these two sections.
- Colors/tokens: white/navy, blue banner, mint/teal, violet, orange, rose and
  cyan surfaces; bold line icons and colored actions. Status stays neutral;
  color conveys topic, never invented assessment severity.
- Image/icon fidelity: approved existing logo retained; installed Lucide icon
  family supplies real library icons. No new bitmap art is required inside
  these report panels, no CSS imitation of a reference image, fake waveform
  or generated report screenshot mounted as UI. Existing guest sidebar is
  unchanged; its missing promotional photo is outside this bounded slice.
- Copy/content: “Your call, clearly.”, “Build your sales skills”, “Your next-call
  plan”, Keep/Change/Practise and Open notes match the requested plain-English
  direction. Eight server labels/statuses/observations and citations remain
  exact. Contract-absent grades, saved checklist and practice recorder are not
  added just because they appeared in a mock.

## Post-fix checks

| Viewport | Main visible / scroll height, both tabs | Lowest skills / plan content | Player top |
| --- | --- | --- | --- |
| 1440×900 | 838 / 838 | 742.98 / 692 | 819.22 |
| 1024×626 | 564 / 564 | 512.06 / 524.52 | 545.22 |
| 390×844 | 698 / 698 | 555 / 557.97 | 683.48 |
| 375×667 | 521 / 521 | 505 / 496.08 | 506.48 |

Both skills pages, all mobile plan panels, all eight reader positions,
Next-disabled boundary, Shift+Tab/Tab containment, Escape/focus restoration and
unclamped print were exercised. No page errors in the synthetic browser run.
Unit suite212/212; independent focused rerun69/69; lint/build passed.

## Known outside-slice gaps

Overview still needs its compact carousel/layout pass; current synthetic
Overview main content scrolls. Moments remains a transcript-based view, not the
approved semantic-moment master/detail design. Do not interpret this document
as all-report or all-app completion. Native devices, real-call provider output,
screen-reader certification, browser zoom and integrated learner screenshots
are not proved by desktop viewport emulation.

## Implementation checklist

- [x] Compare normalized source + render for desktop and mobile.
- [x] Fix measured player overlap and retest every compact panel.
- [x] Preserve actual contract fields and complete reader/print access.
- [x] Complete independent review and executable checks.
- [x] Record remaining report-wide work separately.

Follow-up P3: increase short-phone separation between the skills pager and
player when additional vertical space is available; current hit areas do not
overlap. No actionable P0/P1/P2 remains in this bounded slice.

final result: passed

---

## 2026-09-16 — Delayed processing update (bounded follow-up)

Selected source: the existing generated processing desktop/mobile references
under `docs/design/sales-xray-20260916`, visually inspected with the compiled
candidate. Reuses the approved white/navy and coloured stage-card composition.
No brand reset, invented server state or new raster asset.

After one minute with an unchanged progress projection, local copy changes
inside its reserved text area. The actual stage remains visible. Identical
polls do not reset the timer; new progress does. Paused/error/report states
take precedence. Hidden copy is excluded from the accessibility tree.

Compiled candidate loopback3125, Chromium, synthetic API fixtures, reduced
motion: 28 state/viewport checks passed across1440×900,1024×626,390×844,375×667.
All document/main scroll heights equal their available viewport heights.
Twelve timed transitions measured identical panel child rectangles before and
after; twelve delayed-to-held transitions fit and made zero mutations.
Baseline and candidate screenshots/data:
`docs/evidence/sales-xray-processing-delay-20260916/`.

Full frontend221/221; independent focused50/50; lint/TypeScript/build passed.
No open P0/P1/P2 in this bounded change. General offline/poll-error recovery,
Overview/Moments/Admin and real-provider evidence remain separate open work.
Detailed scope: `docs/evidence/20260916_SALES_XRAY_PROCESSING_DELAY.md`.

final result: passed

---

## 2026-09-16 — Overview, Moments and focused review

Selected user Sep16 generated Overview/Moments/modal references were implemented
as real source-backed components: white/navy hierarchy, mint/violet/orange/blue
cards, library line icons, desktop grid and mobile card navigation. Existing
server labels, quotes, provenance and missing-data states remain authoritative.
No fake waveform, scores or semantic categorisation to fill the mockup.

Fixed measured Moments/player overlap and a long-Plan short-phone overlap.
Independent P2 qualifier-hiding finding fixed; full source caveats preserved.
Inherited open-dialog print clipping and hidden detail-tab printing corrected.

Compiled loopback3130 Chromium: standard and long fixtures each passed70 result
records across1440×900,1024×626,390×844,375×667. Four report tabs, all mobile
Overview cards, compact desktop pages, all12 fixture review points, modal focus
restoration, transcript access and full print verified. Workspace/document fit;
long detailed readers intentionally have internal bounded scrolling.
Frontend238/238; independent37/37; lint/build/TypeScript passed. No open P0–P2
in this bounded report slice. Real-provider/audio E2E, native devices, zoom,
screen-reader certification, Admin and prospect feature remain separate work.

Evidence and exact measurements:
`docs/evidence/20260916_SALES_XRAY_REPORT_OVERVIEW_MOMENTS.md` and
`docs/evidence/sales-xray-report-20260916/`.

final result: passed

---

## 2026-09-16 — Actual-shell dialog correction

Production20:53 report confirmed identity-transform/scroll containment clipping
the shared fixed dialog. Reduced-motion QA had masked the root cause. Native
top-layer dialog preserves styles and escapes this containing block. Normal-motion
compiled checks now include1536×674 and force400px shell scroll:20 sheet-position
invariance checks passed across5viewports,105total report result records.
Full238tests (2workers), independent27tests and build/TypeScript passed.
Actual candidate private-call verification remains release-coordinator owned:
normal local Google login requested a passkey and was not bypassed.
Evidence: `docs/evidence/20260916_SALES_XRAY_TOP_LAYER_DIALOG.md`.

Local correction result: passed. Production verification: pending.
