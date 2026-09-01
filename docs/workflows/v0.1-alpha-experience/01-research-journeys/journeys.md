# End-to-end journeys

## Journey index

| Journey                            | Actor and goal                                                   | Entry                                | Exit                                                   |
| ---------------------------------- | ---------------------------------------------------------------- | ------------------------------------ | ------------------------------------------------------ |
| `JRN-01` Account to first value    | anonymous/unverified person becomes an account-ready learner     | public course, `/register`, `/login` | verified session and onboarding completed or skipped   |
| `JRN-02` Identity recovery         | person safely recovers verification, password, OAuth, or session | auth error or expired session        | fresh session or clear terminal/support path           |
| `JRN-03` Module 1 learning loop    | learner makes and preserves real progress                        | `/home` or enrolled course path      | Module 1 completion evaluated and next state explained |
| `JRN-04` Profile and appearance    | learner reviews bounded profile and controls theme               | profile menu or `/settings`          | saved profile or locally applied theme with status     |
| `JRN-05` Resilient web/PWA use     | learner continues safely on Edge or iOS under interruption       | any learner route                    | recovered current state without fabricated mutation    |
| `JRN-06` Separate admin operations | AC operator diagnoses or performs a named command safely         | admin host + Access + app session    | authorized read or audited command result              |

## `JRN-01` — Account to first value

### `STG-AUTH-01` Discover and choose entry

1. Anonymous visitor opens `COURSE-01` at `/programs/{slug}`.
2. The page uses only the published public catalog projection. It presents the
   real Module 1 topology and does not imply enrollment.
3. “Start free course” routes to `AUTH-02` when no verified session exists.
4. A safe intended destination may be preserved, but only an allowlisted
   same-origin route is accepted after authentication.

### `STG-AUTH-02` Register with explicit consent

1. `AUTH-02` asks for email and password using password-manager-compatible
   semantics and the exact active consent text/version.
2. Consent covers 18+, Terms, Privacy, and required operational email. The
   checkbox is not preselected.
3. Google registration is enabled only from the consent-recording start path.
   Ordinary Google login remains existing-identity-only.
4. Submit enters a named processing state. The acknowledgement is
   existence-neutral, including duplicate-address cases.
5. The next frontstage state is `AUTH-03` verification pending.

### `STG-AUTH-03` Verify and establish session

1. `AUTH-03` consumes a fragment-delivered challenge token; tokens never
   appear in query strings, analytics, logs, screenshots, or this package.
2. Valid verification activates the email fact, consumes sibling challenges,
   issues a host-only session, and advances to `ONB-01`.
3. Missing, expired, or consumed links provide resend/restart paths without
   exposing whether another account exists.

### `STG-ONB-01` Progressive onboarding

1. `ONB-01` loads the canonical self-scoped profile and revision.
2. Step 1 asks “Where are you practicing?” with `sales`, `founder`,
   `customer_success`, or `other`.
3. Step 2 asks for a free-text learning goal, maximum 240 characters.
4. Step 3 optionally captures a current situation (maximum 500 characters)
   and weekly minutes (15-1200, five-minute increment).
5. Save uses an optimistic revision. A conflict reloads the newer record;
   stale input is not silently allowed to overwrite it.
6. The learner may skip. No recommendation, score, entitlement, or learner
   identity is inferred from answers.
7. Completion or skip advances to the published catalog/course entry, not an
   invented personalized program.

### `STG-ENR-01` Enrollment boundary

1. The learner explicitly chooses `Start free course` from `COURSE-01` or the
   learner-home entry. Page view, login, analytics, or consent alone does not
   trigger enrollment.
2. The server requires an active, email-verified person; the exact recorded
   current consent version and timestamp; and an active `learner` membership
   in `AC_PUBLIC_LEARNER_TENANT_ID`, which must be distinct from
   `AC_OPERATIONS_TENANT_ID`.
3. Only the exact published global program slug
   `authority-closers-free-course` may create or reuse a canonical eligibility
   fact under `AC-FREE-SELF-ATTESTATION-v1`.
4. Evidence records the consent version/timestamp and explicit
   `start_free_course` action. It records no email, password, provider token,
   or analytics-derived authority.
5. Eligibility creation/reuse and idempotent enrollment share the caller-owned
   transaction. Existing positive facts are reused without overwrite;
   negative, expired, stale-consent, wrong-course, inactive, unverified, or
   non-learner inputs fail closed.
6. `GAP-ENR-001` is superseded by this accepted contract. Exact-current
   staging and browser evidence remain runtime pending.

## `JRN-02` — Identity and session recovery

### `STG-REC-01` Login and verification recovery

- `AUTH-01` returns one safe invalid-credentials message for an unknown address
  or wrong password.
- An eligible unverified password account receives a verification-required
  state with resend. The public response remains existence-neutral.
- Provider outage is retryable and does not erase entered email.

### `STG-REC-02` Password recovery

1. `AUTH-04` accepts an email and always returns the same acknowledgement.
2. A valid reset link opens `AUTH-05`; new password and confirmation must
   match and support password managers.
3. Successful reset revokes every active session. The learner signs in again.
4. Expired, missing, or consumed links retain a safe request-another-link path.

### `STG-REC-03` Google recovery

- `AUTH-06` renders allowlisted same-origin states for missing registration,
  missing/current consent, provider rejection, and provider outage.
- Invalid state, cookie, host, or callback shape fails closed and never shows
  OAuth codes, provider payloads, internal details, or tokens.
- Account selection and identity transmission remain user actions; no workflow
  automation silently selects a signed-in Google identity.

### `STG-REC-04` Session expiry

1. Any protected request returning canonical unauthorized state routes to
   `AUTH-07`.
2. The screen reassures the learner about server-saved work and accurately
   distinguishes unsaved browser input.
3. Sign-in preserves only an allowlisted intended route.
4. A draft conflict after reauthentication uses the activity's revision
   recovery; it does not silently replace server work.

## `JRN-03` — Module 1 learning loop

### `STG-LEARN-01` Home and course path

1. `HOME-01` resolves the server-owned learner context and enrollment
   projection.
2. With active enrollment, “Continue learning” opens `COURSE-02` with the
   pinned program version and authoritative `0..5` Module 1 completion count.
3. Without enrollment, the page is an honest first-use state linked to the
   published course. It does not say “no course exists” when the projection is
   unavailable.
4. `COURSE-02` and `MOD-01` show each activity in required order with complete,
   in-progress, available, or locked state and a server-provided reason.

### `STG-LEARN-02` `ACT-01` Watch

1. The player exposes title, duration if known, captions/transcript status,
   playback error, unique-coverage progress, and the next required action.
2. Opening or pressing Play never marks complete.
3. Completion uses versioned server-authoritative watched intervals. The
   controlled operating default is 90% unique instructional coverage, not a
   mastery score.
4. Media unavailable or evidence pending remains visible and retryable.
   `GAP-MEDIA-001` blocks claims of real playback completeness.

### `STG-LEARN-03` `ACT-02` Reflect

1. The learner writes a private workbook response.
2. Saving states are explicit: saving, saved with timestamp/revision, failed,
   offline/unsaved, and conflict.
3. Navigation/session expiry must not claim browser-only text is durable.
4. Reopening restores the server draft. Completion follows the configured
   evidence policy and is not a score.

### `STG-LEARN-04` `ACT-03` Implement

1. The screen separates instructions, acknowledged start, evidence/reflection,
   and configured completion.
2. v0.1 accepts the bounded text evidence contract only. It does not fabricate
   media upload, external review, or proof that real-world behavior occurred.
3. Duplicate submit is idempotent; retry shows the same canonical result.

### `STG-LEARN-05` `ACT-04` Review

- The learner records an observed pattern after the challenge.
- The UI does not fabricate a coach, reviewer assignment, AI judgment, score,
  or feedback if none exists.
- Completion records self-scoped evidence according to the configured policy.

### `STG-LEARN-06` `ACT-05` Improve

- The learner records one explicit behavior, correction, or next action.
- Completing the activity requests server-side Module 1 evaluation.
- `PROG-01` and the course path show the resulting authoritative state. Later
  modules are unlocked only when configured prerequisites and real content
  permit it; this package does not invent Modules 2-4 activity breadth.

## `JRN-04` — Profile, settings, and appearance

### `STG-SET-01` Profile

- `SET-01` now has a current `/settings` route and implementation candidate for
  Appearance, verified account facts, learning profile, and session actions.
- `SET-03` shows the bounded learning profile and routes edits through the
  existing revisioned `/onboarding` flow rather than inventing a second write
  contract.
- Display identity fields that are not backed by an approved mutation API are
  read-only.

### `STG-SET-02` Theme

1. `SET-02` offers Light, Dark, and System.
2. System follows the active user-agent/OS color preference.
3. The selection changes semantic tokens across the current learner surface;
   content meaning, completion, and status never change with theme.
4. The current implementation stores only the non-sensitive device-local
   choice. Cross-device and learner/admin synchronization are not authorized
   by this package. Exact browser/runtime proof remains pending.

### `STG-SET-03` Security and privacy

- The current settings candidate supports verified-account context and
  sign-out. Password recovery remains on the existing approved identity route;
  no additional settings mutation is inferred.
- Privacy may link only to the existing Terms and Privacy pages. This package
  defines no deletion workflow, retention command, MFA, SSO, or connected-app
  behavior.

## `JRN-05` — Resilient Edge and iOS PWA use

- Navigation and protected data require a secure origin and same-origin
  credentials.
- Loading uses structure-preserving skeletons and named status, not an
  indefinite spinner for business uncertainty.
- Offline may show safe cached read-only data as stale. Mutations are blocked
  unless a specific activity contract supports a durable queue; this package
  does not infer one.
- `SYS-03` at `/offline` contains no protected data and explains reconnect.
- Compact layouts keep a visible top context and safe-area-aware bottom
  navigation; wide layouts use a persistent rail and readable content width.
- Installed Edge and iOS Home Screen modes preserve deep links, theme metadata,
  session-expiry recovery, and visible browser capability limitations.

## `JRN-06` — Separate admin foundation

1. The operator enters the admin hostname, passes Cloudflare Access (where
   configured), then establishes the distinct AC product session.
2. `ADM-01` resolves selected tenant, membership, named permissions, and data
   freshness. Missing metrics are “unavailable,” never zero.
3. `ADM-02` People and `ADM-03` Catalog are read-first. No directory, assignment,
   or content record is fabricated.
4. `ADM-04` Learning Operations diagnoses enrollment/progress state.
5. `ADM-05` Correction and `ADM-06` Grant are named commands with tenant,
   purpose, reason, idempotency, confirmation, and append-only audit history.
6. Permission denial does not reveal another tenant's resource existence.
7. Routine recovery never uses raw SQL or makes VPS/production state
   authoritative.

Broad analytics, reporting, billing, integrations, media library, activity
authoring, SSO/SCIM, B2B management, autonomous scoring, and destructive
view-as behavior remain outside this admin foundation.
