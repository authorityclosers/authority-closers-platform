# UX/UI behavioral specification

Status: implementation-facing reference for `AC-WF-V01-ALPHA`.

## 1. State model

Every rendered state combines three layers:

1. **Presentation state** — ready, loading, processing, empty, validation,
   retryable error, terminal error, offline/stale, permission denied, locked,
   partial, success, or session expired.
2. **Canonical business state** — identity verification/session, onboarding
   revision/status, enrollment/version, progress/evidence/completion, or admin
   command/audit state.
3. **Service recovery state** — what is safe now, what input is preserved, who
   owns the next action, and how the final state is verified.

A presentation label such as “error” or “partial” never substitutes for the
canonical business state.

## 2. Route and screen register

`contract` means present in the controlled repository route/screen contract.
`implementation_candidate` means a bounded current route/component now exists
but this package has not supplied exact-release browser or staging proof.
`runtime_pending` means the implementation and accepted behavior align closely
enough to validate next, without claiming a live pass. `same route` means an
activity renderer selected from canonical activity kind, not a new hard-coded
page route.

| Screen ID   | Route/surface                            | Actor               | Status                     | Primary responsibility                                               |
| ----------- | ---------------------------------------- | ------------------- | -------------------------- | -------------------------------------------------------------------- |
| `AUTH-01`   | `/login`                                 | anonymous           | contract                   | password and existing-person Google login                            |
| `AUTH-02`   | `/register`                              | anonymous           | contract                   | consent-gated password/Google registration                           |
| `AUTH-03`   | `/verify-email`                          | unverified          | contract                   | consume/resend verification challenge                                |
| `AUTH-04`   | `/forgot-password`                       | anonymous           | contract                   | existence-neutral recovery request                                   |
| `AUTH-05`   | `/reset-password`                        | anonymous           | contract                   | fragment-token password reset and session revocation                 |
| `AUTH-06`   | `/auth/callback`                         | anonymous/person    | contract                   | allowlisted Google recovery result                                   |
| `AUTH-07`   | `/session-expired`                       | learner/admin       | contract                   | reauthenticate and safely resume                                     |
| `ONB-01`    | `/onboarding`                            | verified learner    | contract                   | three-step bounded self-profile                                      |
| `HOME-01`   | `/home`                                  | learner             | contract                   | current enrollment, continue action, first-use/recovery              |
| `COURSE-01` | `/programs/{slug}`                       | public/learner      | contract                   | published course facts and explicit free-enrollment entry            |
| `COURSE-02` | `/learn/{programSlug}`                   | enrolled learner    | contract                   | version-pinned path and progress                                     |
| `MOD-01`    | `/learn/{programSlug}/module/{moduleId}` | enrolled learner    | contract                   | ordered activities and prerequisite locks                            |
| `ACT-01`    | `/activity/{activityId}`                 | learner             | same route                 | video evidence and completion status                                 |
| `ACT-02`    | `/activity/{activityId}`                 | learner             | same route                 | private reflection/workbook draft                                    |
| `ACT-03`    | `/activity/{activityId}`                 | learner             | same route                 | bounded implementation evidence                                      |
| `ACT-04`    | `/activity/{activityId}`                 | learner             | same route                 | learner-observed review                                              |
| `ACT-05`    | `/activity/{activityId}`                 | learner             | same route                 | explicit improvement action                                          |
| `PROG-01`   | `/progress`                              | learner             | `runtime_pending`          | honest program/module/activity projection                            |
| `SET-01`    | `/settings` Verified account card       | learner             | `runtime_pending`          | verified-account facts and bounded profile context                   |
| `SET-02`    | `/settings` Appearance card              | learner             | `runtime_pending`          | device-local Light/Dark/System theme mode and advanced appearance variants |
| `SET-03`    | `/settings` Learning setup card          | learner             | `runtime_pending`          | read bounded profile; edit through revisioned onboarding             |
| `SET-04`    | `/settings` Security/privacy card        | learner             | `implementation_candidate` | existing recovery, Terms, and Privacy routes only                    |
| `SET-05`    | `/settings` Session card                 | learner             | `implementation_candidate` | current session facts and same-origin sign-out                       |
| `SYS-01`    | current route                            | any                 | contract family            | structure-preserving loading/processing                              |
| `SYS-02`    | current route                            | any                 | contract family            | retryable/terminal failure and support path                          |
| `SYS-03`    | `/offline`                               | any                 | contract                   | static, no-protected-data connectivity boundary                      |
| `SYS-04`    | current route                            | learner             | contract family            | prerequisite/access locked explanation                               |
| `ADM-01`    | admin `/`                                | AC operator         | candidate foundation       | tenant-aware overview with truthful unknowns                         |
| `ADM-02`    | admin `/people`                          | authorized operator | candidate foundation       | people/membership read boundary                                      |
| `ADM-03`    | admin `/catalog`                         | authorized operator | candidate foundation       | immutable catalog/version visibility                                 |
| `ADM-04`    | admin `/learning-operations`             | authorized operator | candidate foundation       | learning diagnosis and named actions                                 |
| `ADM-05`    | admin `/people/corrections`              | authorized operator | candidate foundation       | reasoned append-safe correction command                              |
| `ADM-06`    | admin `/people/grants`                   | authorized operator | candidate foundation       | reasoned enrollment/access grant command                             |

No screen in this package authorizes `/library`, broad search, calendar,
practice engines, certificates as a launch claim, billing, integrations,
notifications, tenant branding, broad reporting, or enterprise management.

## 3. Shell and navigation

### Learner wide shell

- Persistent rail: Home, My learning, Progress, Settings.
- “My learning” resolves to the active/pinned course path; it does not expose a
  fabricated broad assignment collection.
- Library/Search are absent or explicitly unavailable; a disabled decorative
  destination must not look actionable.
- Header identifies current context and provides Profile/Settings and Sign out.
- Main content uses a readable maximum width; activity work can use a wider
  split layout when the secondary pane is useful.

### Learner compact shell

- One-column primary content.
- Safe-area-aware bottom navigation for Home, Learning, Progress, and More.
- Settings is available through More/Profile and remains keyboard/screen-reader
  reachable.
- Bottom navigation never covers save state, captions, form errors, or the
  current primary action.

### Admin shell

- Separate hostname/app, visual shell, and session boundary.
- Desktop-first information density; compact mode uses cards/disclosure rather
  than forcing wide tables into horizontal overflow.
- Current tenant, role/permission, freshness, and audit context stay visible.
- Learner theme preference cannot weaken admin warning/danger semantics.

## 4. Authentication and consent

### `AUTH-01` Login

Structure: AuthShell, product identity, email, password, show-password control,
submit, existing-person Google action, forgot-password link, register link,
inline status region.

- Use `autocomplete=email` and `autocomplete=current-password`.
- Preserve email through retry; never preserve/display the password after a
  rejected navigation or reload.
- Invalid credentials are one existence-neutral response.
- Verification required provides resend without revealing unrelated identity.
- Successful login resolves server context, then routes to safe intended
  destination, onboarding, or home according to canonical response.

### `AUTH-02` Registration

Structure: AuthShell split composition on wide screens, email, new password,
explicit unchecked consent, submit, consent-gated Google registration,
sign-in link, status region.

- Consent text/version comes from reviewed environment configuration.
- Consent records 18+, Terms, Privacy, and required operational email only;
  marketing consent is not bundled.
- A duplicate address receives the same verification acknowledgement.
- Google registration binds the exact consent version into the signed OAuth
  transaction and revalidates before provider exchange.

### Verification and recovery

- `AUTH-03` and `AUTH-05` consume fragment tokens and clear them from visible
  browser state after capture. No token is placed in query parameters.
- `AUTH-04` and verification resend always acknowledge safely.
- Reset success revokes active sessions and requires new authentication.
- `AUTH-06` recovery result values are a closed allowlist; provider payloads,
  codes, addresses, and internal exception text never render.
- `AUTH-07` distinguishes server-saved work from input that exists only in the
  current browser.

## 5. Progressive onboarding

`ONB-01` is one route with three persisted steps and a completion/skip state.

| Step | Field                | Required             | Contract                                                                            |
| ---- | -------------------- | -------------------- | ----------------------------------------------------------------------------------- |
| 1    | `experience_context` | required to complete | enum UI values: `sales`, `founder`, `customer_success`, `other`; max 64 server-side |
| 2    | `learning_goal`      | required to complete | free text, max 240                                                                  |
| 3    | `practice_situation` | optional             | free text, max 500                                                                  |
| 3    | `weekly_minutes`     | optional             | integer 15-1200, UI step 5                                                          |

- Statuses: `not_started`, `in_progress`, `completed`, `skipped`.
- Saves require `If-Match: onboarding-revision-N` semantics.
- Step 1 may skip. Step 2/3 provide Back and Save & continue/Finish.
- A stale save returns conflict. The frontstage offers Reload latest and does
  not discard a local draft until the learner makes the choice.
- Answers inform future reviewed UX work only; v0.1 does not create a score,
  persona identity, authorization role, or unreviewed recommendation.

## 6. Home, course, and Module 1

### `HOME-01`

Ready structure: welcome/context, Continue learning card, Module 1 progress,
next required action, concise profile card, and recoverable alerts.

- Data comes from `/v1/me`, server-selected context, enrollment, catalog, and
  canonical progress projections.
- If no active enrollment exists, show a first-use course entry. If the
  projection failed, show retry rather than “no enrollment.”
- Missing data is unavailable, never zero.

### `COURSE-01`

- Shows published title, description, four shift/module titles when present in
  the published seed, Module 1 activity topology, version, and free entry.
- Enrollment begins only from the explicit `Start free course` action. Page
  view, login, consent acceptance, provider state, or analytics never starts it.
- For the exact published global slug `authority-closers-free-course`, the
  caller-owned transaction requires an active email-verified person, exact
  recorded current consent version/timestamp, and an active `learner`
  membership in the active public learner tenant, distinct from the operations
  tenant. It creates or reuses `AC-FREE-SELF-ATTESTATION-v1` and then enrolls.
- Existing positive facts are reused and never overwritten. Negative, expired,
  stale-consent, wrong-course, inactive, unverified, non-learner, or
  wrong-tenant inputs fail closed. `GAP-ENR-001` is superseded; runtime proof is
  still pending.
- Public detail does not expose protected activity payload or learner progress.

### `COURSE-02` and `MOD-01`

- Show pinned version, ordered modules/activities, progress count, current/next
  activity, and exact lock reason.
- The Module 1 sequence is `ACT-01` Video, `ACT-02` Reflection, `ACT-03`
  Implementation Challenge, `ACT-04` Review, `ACT-05` Improve.
- Modules 2-4 are topology-only in this package. Their module titles/order may
  render from the published projection, but no activities, completion, unlock,
  or content semantics are invented.
- Later module unlock is course configuration, not a platform-wide rule.

## 7. Activity shell and evidence

Every activity renderer sits in one `ActivityShell` with breadcrumb/back,
position in module, activity type/title, status, save/evidence state, primary
action, and next-action explanation.

### `ACT-01` Video

- Display coverage as participation evidence, never mastery.
- The configured completion policy/version is server authoritative.
- Page open, play, seek, replay, or raw client position cannot complete it.
- Captions/transcript availability and media/provider failure are explicit.
- “Evidence processing” remains pending until the canonical projection changes.

### `ACT-02` Reflection

- Textarea has visible label, prompt, character limit/status, and save state.
- States: restored, dirty, saving, saved/revision, save failed, offline/unsaved,
  conflict, completed.
- Offline does not promise a durable queue. Safe in-memory preservation may be
  described only for the current page; reconnect is required for canonical
  save unless a separately tested queue contract is approved.

### `ACT-03` Implementation

- Separate instructions, acknowledgement/start, bounded text evidence, and
  completion status.
- Do not claim external verification of real-world behavior.
- No upload control appears without approved upload/media policy and runtime.

### `ACT-04` Review and `ACT-05` Improve

- Review captures the learner's observed pattern.
- Improve captures one explicit behavior/correction/next action.
- Neither surface fabricates a coach response, AI judgment, score, or mastery.

## 8. Progress

`PROG-01` has a current route/component implementation and is
`runtime_pending`; this package supplies no exact-release browser or staging
proof.

- Present program, module, and activity facts from canonical projections.
- Show counts and required-item status; missing projection is unavailable.
- Do not include hidden composite score, learner ranking, streak shame, broad
  analytics, or inferred skill mastery.
- Activity links deep-link to the permitted version-pinned path.
- Module 1 may show its five activity facts. Modules 2-4 remain topology-only
  unless a future controlled contract and published runtime projection add
  authorized activity breadth.

## 9. Profile, settings, and theme

`SET-01` through `SET-05` have a current bounded route/component
interpretation. Their cards are:

- Verified account: display name, email, role, and verification facts are
  read-only unless an existing identity mutation contract says otherwise.
- Learning setup (`SET-03`): show fields already defined by `ONB-01`; edits
  route to the existing revisioned onboarding flow.
- Appearance (`SET-02`): Light, Dark, and System theme mode, plus bounded named
  presets, accent palette, display density, and motion preferences.
- Security/privacy (`SET-04`): existing password recovery and Terms/Privacy
  routes only; no MFA or SSO behavior and no deletion or retention workflow.
- Session (`SET-05`): current session facts, same-origin sign-out, and existing
  session-expiry recovery only.

Theme behavior:

- Default to Light for a person/device without a recorded selection.
- Resolve System from `prefers-color-scheme`; communicate current resolved
  theme without changing the saved choice.
- Keep named presets and accent, density, and motion choices as presentation
  variants in the current browser only; they are never account, tenant, or
  authority state.
- Apply semantic tokens to the current learner surface. Admin preference sync
  is not authorized by this device-local implementation.
- Update user-agent `color-scheme`; verify first-paint behavior separately
  because current code/runtime evidence has not proven a flash-free load.
- Never store a secret or business state in theme storage.
- Current device persistence uses the non-sensitive local preference keys
  `ac-appearance-theme`, `ac-appearance-accent`, `ac-appearance-density`, and
  `ac-appearance-motion`. Cross-device/account persistence and learner/admin
  synchronization are outside the current contract, not inferred gaps to fill.

## 10. Universal states

| State             | Required frontstage behavior                                                                                |
| ----------------- | ----------------------------------------------------------------------------------------------------------- |
| Loading           | preserve page structure; announce once; no indefinite business-state spinner                                |
| Processing        | identify the operation; prevent unsafe duplicate mutation; allow safe navigation only when contract permits |
| Empty             | explain why the authorized collection is empty and provide one valid next action                            |
| Validation        | associate message with field; preserve valid input; focus/summary goes to first error                       |
| Retryable error   | state what failed, what is preserved, and a bounded Retry action                                            |
| Terminal error    | explain safe support/restart path; do not loop Retry                                                        |
| Offline/stale     | label cached data stale; block unsupported mutations; show reconnect path                                   |
| Permission denied | do not reveal protected resource existence; route to role-appropriate surface                               |
| Locked            | show prerequisite/access condition without protected payload                                                |
| Session expired   | distinguish durable vs browser-only work; reauthenticate to safe return path                                |
| Success           | confirm canonical result and next step; do not rely on color alone                                          |

## 11. Responsive and PWA behavior

- Compact: below 600px, single column, 390px no horizontal overflow, full-width
  primary actions, safe-area padding, touch targets designed to 44px intent.
- Medium: 600-1023px, compact navigation with wider content/forms.
- Wide: 1024px and above, persistent learner rail where useful; admin rail and
  dense tables; readable activity text width.
- At 200% zoom, essential content/actions reflow without two-dimensional
  scrolling except intrinsically two-dimensional data.
- Edge installed mode and iOS standalone mode preserve route, offline,
  theme-color, focus, session, and safe-area behavior.
- Service worker may cache the public/app shell and approved static assets; it
  must not make protected responses broadly cacheable or invent offline writes.
- Update availability is announced non-destructively; do not reload over dirty
  learner work.

## 12. Admin boundary

- Admin hostname and learner hostname use separate surface cookies/audiences.
- Every read resolves selected tenant and permission server-side.
- Every mutation is a named command with purpose/reason, idempotency, audit,
  and explicit confirmation where risk warrants it.
- Corrections supersede history; they never overwrite audit-critical facts.
- Grant state is access/provenance, never a fabricated payment.
- Unknown counts are unavailable. Analytics events are not canonical admin
  state.
- Cloudflare Access is an edge control, not a substitute for AC application
  authorization.

## 13. Analytics and privacy

Allowed event families include registration started/created/verified, login
result category, onboarding save/skip/complete, free-enrollment result,
program/module/activity opened, draft save result, activity/module completion,
offline/retry, support requested, and provider failure category.

- Events use stable actor/tenant/context identifiers according to privacy
  policy; examples never include raw email, password, token, free-text answer,
  OAuth code, cookie, or evidence body.
- Analytics never creates progress, access, score, payment, or completion.
- Theme change may be measured only as a non-sensitive preference category if
  telemetry review approves it.

## 14. Ownership and recovery

| Domain            | Canonical owner                                                     | Frontstage recovery owner                                                                   |
| ----------------- | ------------------------------------------------------------------- | ------------------------------------------------------------------------------------------- |
| Identity/session  | identity application + database                                     | learner self-service, then support                                                          |
| Consent           | append-safe consent record                                          | learner re-consent through approved flow                                                    |
| Onboarding        | person profile + revision                                           | learner reload/merge choice                                                                 |
| Enrollment/access | enrollment/access application plus ADR 0028 self-attestation policy | learner retry; approved identity/consent/membership recovery; authorized operator diagnosis |
| Learning progress | progress/evidence services                                          | learner retry/resume; learning operations                                                   |
| Theme             | device-local presentation preference only                           | learner/device; no account or cross-app sync inferred                                       |
| Admin command     | named application command + audit                                   | authorized operator, then technical runbook                                                 |

No recovery path in this specification authorizes raw SQL, direct production
state repair, secret exposure, or founder intervention for a routine case.
