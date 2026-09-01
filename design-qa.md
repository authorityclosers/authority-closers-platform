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
