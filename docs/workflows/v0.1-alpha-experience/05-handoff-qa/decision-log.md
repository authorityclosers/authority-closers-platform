# Decision log

Decisions are append-safe. A later change adds a superseding entry and updates
affected artifacts; it does not silently rewrite provenance.

## Inherited concept evaluation

No new ideation set was generated because the controlled Drive package already
contains and selects three independent directions. Reopening that decision
would contradict the approved source boundary.

| Direction    | Task fit                                                                           | Accessibility/responsiveness                                          | Extensibility/risk                                              | Decision |
| ------------ | ---------------------------------------------------------------------------------- | --------------------------------------------------------------------- | --------------------------------------------------------------- | -------- |
| Clarity Grid | strongest for clear next action, state visibility, learning shell, and dense admin | explicit compact/wide references; semantic structure remains testable | reusable across learner/admin without inventing product breadth | selected |
| Study OS     | editorial learning emphasis                                                        | reserve evidence only                                                 | mixing it would fragment the active system                      | reserve  |
| Signal Path  | practice/analytics emphasis                                                        | reserve evidence only                                                 | risks implying practice/analytics breadth outside v0.1          | reserve  |

## `DEC-001` — Select Clarity Grid

- Status: locked for v0.1 reference work.
- Decision: use Direction A / Clarity Grid for auth, onboarding, learner, state,
  settings, and separate admin foundation.
- Basis: Drive UI implementation matrix and exact asset ID
  `1VOgXqLvaslXPwYM8bzqboUVQe-JYdT39`.
- Consequence: Study OS and Signal Path remain reserves. No mixed direction.

## `DEC-002` — Keep v0.1 learner navigation bounded

- Status: locked.
- Decision: Home, My learning, Progress, and Settings are the active workflow
  destinations. Broad Library/Search/Calendar/Practice are absent or truthfully
  unavailable.
- Basis: controlled IA, current user request, and Drive extension register.
- Consequence: no decorative tab may imply a live extension capability.

## `DEC-003` — Reuse exact bounded onboarding fields

- Status: locked.
- Decision: three steps capture experience context, learning goal, optional
  current situation, and optional weekly minutes using revisioned save/skip.
- Basis: current onboarding API/domain/UI contract and route contract.
- Consequence: no job title, income, company, phone, persona, skill score,
  recommendation, or entitlement is added.

## `DEC-004` — Model Module 1 as one permanent activity lifecycle

- Status: locked.
- Decision: `VIDEO -> REFLECTION -> IMPLEMENTATION_CHALLENGE -> REVIEW ->
IMPROVE` uses one activity route and canonical evidence/progress lifecycle.
- Basis: AC-IMP-04 and repository route contract.
- Consequence: no five unrelated hard-coded product page semantics.

## `DEC-005` — Add a bounded settings target

- Historical status: proposed workflow target; implementation was blocked by
  `GAP-SET-001`. Superseded by `DEC-015` after current route inspection.
- Decision: `/settings` contains Profile, Appearance, Security, and Privacy.
- Basis: explicit current user decision plus controlled IA `/settings`.
- Conflict: current repository route/screen contract omits `/settings`; Drive
  settings/notifications/branding images are marked extension.
- Resolution: include only fields/actions backed by existing identity/profile
  contracts and record the route promotion/runtime gap. Do not include tenant
  branding, notifications, SSO/SCIM, integrations, or billing.

## `DEC-006` — Light/Dark/System changes presentation only

- Historical status: current-user decision; persistence gap was open.
  Superseded by `DEC-015` for the device-local implementation candidate.
- Decision: offer Light, Dark, System. System follows user-agent/OS preference.
  Apply semantic tokens globally within the current product surface.
- Basis: explicit current user decision, controlled semantic-token UI system,
  and current web-platform guidance.
- Consequence: theme cannot change meaning, state, permissions, or content.
  Device-local persistence is a safe fallback; cross-device and cross-app sync
  require a ratified preference contract (`GAP-THEME-001`).

## `DEC-007` — Progress is factual, not evaluative

- Historical status: proposed workflow target; implementation was blocked by
  `GAP-PROG-001`. Superseded by `DEC-015` after current route inspection.
- Decision: `/progress` shows program/module/activity facts and next action.
- Basis: controlled IA and `PROG-01` approved reference.
- Consequence: no hidden composite, mastery, leaderboard, streak shame, or
  autonomous score.

## `DEC-008` — Separate learner and admin trust boundaries

- Status: locked.
- Decision: admin uses a separate host/app/session and server-authorized named
  permissions; Cloudflare Access is additional, not sufficient authorization.
- Basis: IA, Admin specification, authorization matrix, route contract.
- Consequence: no embedded ERP, shared learner navigation, or client-only role
  gate.

## `DEC-009` — Offline is conservative per mutation

- Status: locked.
- Decision: safe cached reads may be visibly stale. Writes are blocked unless a
  specific durable queue/conflict contract is approved and tested.
- Basis: AC-UXA-01 and Mobile/PWA source.
- Consequence: reflection may preserve current browser text but cannot claim a
  durable offline save/queue.

## `DEC-010` — Visual references are not capability evidence

- Status: locked.
- Decision: asset status remains reference/selected until behavior,
  authorization, runtime, and visual comparison gates pass.
- Basis: Drive UI matrix.
- Consequence: no screenshot or generated image alone can prove auth, progress,
  admin authorization, email, media, PWA, or deployment.

## `DEC-011` — Do not infer self-enrollment eligibility

- Historical status: blocked (`GAP-ENR-001`). Superseded by `DEC-014` after
  ADR 0028 and its implementation sources were accepted.
- Decision: learner consent is not silently transformed into a distinct
  eligibility/age-policy fact.
- Basis: current alpha handoff and provisional source gaps.
- Consequence: the workflow includes an explicit locked/recovery state until a
  versioned policy and runtime evidence exist.

## `DEC-012` — Do not create new raster screens in this docs-only task

- Status: complete.
- Decision: register approved Drive references and provide source-attached
  prompts; do not generate speculative screens.
- Basis: explicit write scope, Clarity Grid source-matching requirement, and the
  package artifact list.
- Consequence: visual production can proceed reproducibly after the behavioral
  and state artifacts are approved.

## `DEC-013` — Keep future breadth as extension contracts

- Status: locked.
- Decision: billing, SSO/SCIM, broad enterprise/B2B, native apps, simulator,
  call review, real-call processing, official autonomous scoring, community,
  broad authoring/media, and certificates as a launch claim are excluded.
- Basis: current user request, AC-IMP-03/04, AGENTS guardrails, Drive matrix.

## `DEC-014` — Consent-backed free-course start supersedes `GAP-ENR-001`

- Status: accepted and implemented in repository; exact-current runtime proof
  pending. This decision supersedes `DEC-011`'s blocked status and
  `GAP-ENR-001` as an active product/engineering gap.
- Decision: only the explicit `Start free course` action may create or reuse a
  canonical eligibility fact for the exact published global program slug
  `authority-closers-free-course` under
  `AC-FREE-SELF-ATTESTATION-v1`.
- Preconditions: active email-verified person; exact recorded current consent
  version and timestamp; active `learner` membership in the exact active
  `AC_PUBLIC_LEARNER_TENANT_ID`; and that tenant is distinct from
  `AC_OPERATIONS_TENANT_ID`.
- Transaction/history: eligibility and enrollment share the caller-owned
  transaction. Existing positive facts are reused and never overwritten;
  negative, expired, stale-consent, wrong-course, inactive, unverified,
  non-learner, or conflicting inputs fail closed.
- Provenance: evidence records consent version/timestamp, the explicit
  `start_free_course` action, and program slug. It records no email, password,
  provider token, or analytics-derived authority.
- Basis: ADR 0028, `docs/contracts/ENVIRONMENT_CONTRACT.md`,
  `packages/python/ac_platform/enrollment/self_attestation.py`, and the current
  learner-web start-action route/component.
- Consequence: no paid, tenant-owned catalog, provider-derived, billing,
  scoring, enterprise, native-app, or direct-SQL access semantics are added.

## `DEC-015` — Current learner routes move progress/settings/theme to validation

- Status: `implementation_candidate` / `runtime_pending`; no live proof claim.
- Decision: `/progress` and `/settings` are current learner-web routes.
  `/progress` renders canonical enrollment/projection facts. `/settings`
  exposes Appearance, verified account facts, learning profile, and session
  actions. Learning-profile edits reuse `/onboarding`.
- Theme decision: `light`, `dark`, and `system` are implemented as a
  non-sensitive device-local preference. `system` follows
  `prefers-color-scheme`; account, cross-device, and learner/admin sync are not
  authorized.
- Bounded candidates: password recovery remains on the existing identity
  route; Privacy may expose only the existing Terms/Privacy pages. No deletion
  workflow, MFA, SSO, integration, notification, or provider semantics are
  inferred.
- Basis: current `apps/learner-web/app/progress`, `settings`, `lib/routes.ts`,
  `components/progress-runtime.tsx`, `components/settings-runtime.tsx`, and
  `components/theme-control.tsx`.
- Consequence: `GAP-PROG-001`, `GAP-SET-001`, and `GAP-THEME-001` are no longer
  unresolved/gap-blocked labels for these candidates. Exact-release runtime,
  accessibility, responsive, and visual-comparison evidence remains pending.

## Current status register

| Item              | Status                                 | Smallest next action                                                                     |
| ----------------- | -------------------------------------- | ---------------------------------------------------------------------------------------- |
| `GAP-ENR-001`     | superseded by `DEC-014`                | prove accepted policy on the exact immutable staging release                             |
| `GAP-MEDIA-001`   | unresolved / capability blocked        | approve media/transcript/caption source and prove real playback/evidence                 |
| `GAP-SET-001`     | `implementation_candidate`             | compare bounded current settings behavior with spec; run exact-release validation        |
| `GAP-THEME-001`   | `runtime_pending` for device-local use | test first paint, focus, storage failure, and both themes; do not infer account sync     |
| `GAP-PROG-001`    | `runtime_pending`                      | prove canonical projection states and Module 2-4 topology-only behavior on exact release |
| `GAP-RUNTIME-001` | unresolved / release evidence pending  | exact-SHA deploy and rerun applicable runtime gates                                      |
