# Free-course authentication continuity — 2026-09-11

The public free-course choice now survives password sign-in, signed Google
return paths, recoverable Google consent/account outcomes, expired sessions
and onboarding before returning to the existing learner enrollment surface.
Registration controls also remain disabled until client readiness, and its
password form explicitly uses POST. This is a separate local checkpoint after
`edb6ea903a4374f3286f333affea12bf795ced40`; it is not a deployment or complete
email/new-device/course-delivery acceptance claim.

## Controlled scope and behavior

Required controlled sources were fetched by exact manifest IDs in the order
recorded in `20260911_UI_RECOVERY_CHECKPOINT.md`. The authority remains BRD
Q037/BR-014/015, AC-IMP-04 sections 5/10/13, WRK-G0-006/021, WRK-G1-003 and
AC-UXA-01 UX-G02/04/09. `V02_REVENUE_RELEASE_CUT.md` prioritizes explicit free
admission, recoverable sign-in and usable mobile journeys. This evidence
supersedes only the missing course-intent observation in
`20260910_REVENUE_JOURNEY_RESUME_ACCEPTANCE.md`; historical evidence is retained.

- Only the existing scalar `authority-closers-free-course` is accepted. Unknown
  values, arrays, duplicate course parameters and URL-shaped input are dropped.
  Navigation targets are fixed local routes; localhost staging handoff retains
  its fixed staging origin.
- All five public course sign-in/registration actions carry this context.
  Password login consults canonical onboarding status before choosing home or
  onboarding. Dashboard loading and expired-session recovery preserve it.
  Settings-origin onboarding still returns to settings.
- Google registration retains explicit consent and one canonical hidden
  `return_path` field for actual GET form submission. Backend recovery copies
  course context only from either exact approved path in the already validated
  signed transaction, across all seven existing recovery branches. Callback
  query parameters do not replace action, consent or transaction destination.
- Membership, onboarding, cookie cleanup, encryption, session issuance and
  explicit enrollment remain their existing authority boundaries. Course input
  does not enroll a learner, complete an activity or grant access. No schema,
  worker, outbox, provider, analytics, payment or scoring behavior is changed.
- Server-rendered registration fields, consent and buttons remain disabled
  until React is ready. Password submission is POST and rejects absent
  readiness, an already pending request or absent consent. Google continuation
  still requires the learner to check consent and is disabled again when it is
  unchecked.

## Validation

All commands ran serially in the existing d2de tree; frontend commands used the
learner package working directory and one Vitest worker. The release task and
this UI task exchanged one heavy-process slot on the constrained laptop.

- Python authentication routes/transactions: **77 passed**. Exact signed course
  destinations, unchanged defaults, consent, forged callback input and recovery
  cleanup are covered.
- Focused learner tests: **209 passed across eight files**, including actual
  password submit ordering/destination, onboarding skip completion, expired
  recovery, explicit enrollment, SSR guards and real render-to-hydration consent
  behavior.
- Learner TypeScript and full ESLint, scoped Prettier, Ruff check/format, and
  changed authentication source mypy passed.
- Full learner regression: **1,578 passed across 87 files**.
- Three Chromium registration regressions passed: default/course consent
  check–uncheck–check with exact GET fields, and JavaScript-disabled credential
  controls. Google start is intercepted with local HTTP 204; these are real
  browser form tests, not actual Google OAuth/provider acceptance.
- Synthetic local password journeys passed at **320 and 1440 px**. Each follows
  public course → keyboard sign-in → password login → course-preserving home →
  keyboard canonical activity. The target comes from `/v1/learning`. Six images
  have no horizontal overflow; no page errors occurred. Each journey observed
  exactly one mutating HTTP request, the password-login POST, and no enrollment
  mutation. This does not claim zero database writes during authentication.
- Independent source review found no P0/P1/P2 defects in the bounded change.
  All six browser images were visually inspected. The mobile public curriculum
  summary has an existing cramped title/count layout; it remains an explicit
  next UI fix, so this checkpoint does not claim complete mobile visual quality.

## Evidence and retained failures

Recovery packet:
`D:/Projects/authority-closers-release-transfer/2026-09-11-recovery`.

- `course-intent-validation-20260911T081553Z`: passing 77 Python tests and the
  first frontend run, whose single HTML attribute-order assertion failed.
- `course-intent-validation-20260911T081742Z`: corrected 204 focused tests and
  static checks before the subsequently added registration readiness coverage.
- `course-intent-validation-20260911T083343Z`: final 209 focused tests, typecheck,
  full learner lint and formatting checks.
- `course-browser-validation-20260911T083607Z`: final three browser tests and
  synthetic journey runner results.
- `course-intent-browser-20260911T083632Z/proof.json`: six images, viewport/theme,
  sixteen runtime file SHA256 values, canonical target and measured requests.
- `course-learner-restart-20260911T083125Z`: preserved prior learner logs and
  managed learner-only restart. API, PostgreSQL, Admin and Coach were preserved.
- `ui-checkpoint-validation-20260911T084539Z`: final full learner suite, 1,578
  passing tests in 87 files.
- `course-intent-checkpoint-paths-20260911.json`: explicit 24-path checkpoint
  allowlist, including seven test files and this evidence document.

The first browser runner stopped after incorrectly testing PowerShell
`LASTEXITCODE` for a successful script-only API stop; it was corrected to use
PowerShell success. The first registration browser run found inert client
interactions; diagnostic clicks produced no React updates, no page errors and
no failed responses. A managed learner restart restored client behavior, but
the exact old development-runtime stall cause is unproved. Separate source
inspection established the missing registration readiness/POST guards, now
covered by regressions. Earlier failed results remain retained and are not
counted as passing acceptance.

## Remaining acceptance boundary

Email verification and new-device navigation still need a separate versioned
verification-email payload/worker/UI slice; existing queued jobs and token,
consent, session and enrollment authority must be preserved. Password reset,
actual Google provider behavior, deployed screenshots, full published media
delivery and the complete Watch–Reflect–Implement–Review–Improve cycle are not
proved here. The release owner reconciles and validates this separate exact
checkpoint; no remote push, merge, migration or deployment was performed by
this UI task.
