# Learner and admin Clarity Grid design QA

## Source visual truth

The approved Drive exports were fetched by exact controlled Drive ID and are
indexed in
`docs/evidence/screenshots/v0.1-staging-exact-5b55a05/README.md`. The primary
comparison family is:

- desktop and mobile learner shell;
- auth registration;
- desktop and mobile course overview;
- mobile reflection;
- desktop implementation evidence;
- admin overview.

The approved direction remains Clarity Grid: white surfaces, navy/ink
structure, indigo actions, restrained borders, compact learning UI, desktop
rail/top bar, and responsive mobile navigation. Controlled route and state
contracts override mockup-only claims for media, reviewers, certificates,
metrics, and future navigation.

## Exact implementation evidence

- Release: `27fafaea1e5de41ae6a830746b1d832b42c7d444`
- Learner: `https://staging.authorityclosers.com`
- Admin: `https://admin-staging.authorityclosers.com`
- API: `https://api-staging.authorityclosers.com`
- Browser: the user-selected authenticated Chrome session
- Browser capture viewport: 1521 × 667 CSS pixels
- Evidence index:
  `docs/evidence/screenshots/v0.1-staging-exact-27fafae/README.md`
- Combined source/implementation review:
  `docs/evidence/screenshots/v0.1-staging-exact-27fafae/comparison-shell-home.png`

The exact-release evidence includes an authenticated learner home with the
server-authorized free course, the full five-step Module 1 loop, a restored
server draft, public catalog and program detail, login, registration,
recovery confirmation, Google-authenticated owner home, and the protected
admin foundation.

## Source plus implementation comparison

The desktop learner shell preserves the approved information hierarchy:
fixed learner rail, top search/action bar, selected Home state, prominent
welcome block, current-course card, and account context. The live home now
surfaces `Authority Closers Free Course` with a working `Continue course`
action and server-authoritative `0 / 5` projection.

The comparison is qualitative rather than pixel-perfect because the approved
desktop export is 1487 × 1058 while the connected Chrome capture is 1521 × 667. No density normalization or crop is presented as a same-viewport pixel
match.

The activity family follows the approved loop language and compact workspace
treatment for VIDEO → REFLECTION → IMPLEMENTATION_CHALLENGE → REVIEW →
IMPROVE. The reflection screen restores the server draft and character count.
Submission and media remain visibly disabled where the controlled server
contracts do not authorize them.

## Findings

- [Resolved] Authenticated desktop ready-state evidence now exists for learner
  home, course path, five activities, Google login landing, and protected
  admin.
- [Resolved] The learner home now discovers the first server-authorized
  published program and shows its real projection; it does not synthesize an
  entitlement or progress record.
- [P1] A current-release authenticated mobile visual pass is still missing.
  The connected Chrome surface did not apply a temporary viewport override,
  so responsive tests and CSS checks are not substituted for a real 390 × 844
  browser capture.
- [P2] Media playback remains provider/policy-gated, and implementation
  evidence submission remains reviewer-gated. The UI states are intentional
  and must not be replaced with fabricated completion or review data.
- [P2] The live v0.1 home is intentionally smaller than the future-rich Drive
  example: weekly goals, calendars, certificates, broad library analytics,
  and enterprise navigation remain extension contracts.

## Verification gates

- Learner tests: 54 passed.
- Learner lint: passed.
- Learner typecheck: passed.
- Prettier check: passed.
- Learner production build: passed.
- Pull-request control-plane workflow `33447263943`: passed.
- Pull-request application workflow `33447263944`: passed.
- Exact-release validation and packaging workflow `33447522610`: passed.
- Staging migrations, five-container health, learner/API/PWA route smoke,
  Cloudflare Access boundary, Google callback binding, and legacy WordPress
  boundary: passed.
- Password login for the dedicated learner: passed.
- Google login for `admin@authorityclosers.com`: passed and landed on `/home`
  with owner context.
- Fresh staging password-recovery mail: delivered through Resend.

## Final result

final result: blocked for complete cross-device visual acceptance

The desktop staging alpha visual slice is accepted for the implemented v0.1
boundary. Complete design acceptance remains blocked only on a current-release
authenticated mobile capture and the intentionally gated media/reviewer
capabilities; it is not blocked on desktop staging authentication or the
Module 1 learner journey.
