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
