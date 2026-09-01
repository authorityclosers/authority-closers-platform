# Source-attached prompt pack

These prompts are handoff inputs, not generated assets. Before using any prompt:

1. Attach the exact Drive reference IDs named in that prompt.
2. Attach `ai-design-context.json` and the relevant rows from
   `state-transition-matrix.csv`.
3. Treat all output as `reference`, never production-approved.
4. Generate each distinct state as a separate asset named
   `{SCREEN-ID}-{state}-{viewport}.png`.
5. Do not add business behavior, navigation, fields, icons, assets, content, or
   future product breadth.

## Prompt 1 — Auth and identity recovery family

Attach:

- `AUTH-01-desktop-registration.png` — `1K9qpP-OTsgyuhJ3mtmZYDj2-7EFv_MJb`
- `AUTH-02-desktop-verification.png` — `1NLx4nRVxS_5bsu9hOMjEHW5Yb25GwNr5`

Prompt:

> Create a source-matched Clarity Grid screen family for Authority Closers
> `AUTH-01` through `AUTH-07` at 1440x900 and 390x844. Preserve the approved
> split/stacked composition, hierarchy, spacing, radius, icon language, and
> restrained blue/neutral system. Use only the behaviors and copy constraints
> in the attached state matrix: password login, explicit unchecked 18+ / Terms
> / Privacy / operational-email consent, consent-gated Google registration,
> existing-person Google login, verification pending/success/expired, neutral
> recovery acknowledgement, reset, allowlisted OAuth recovery, and session
> expiry. Create separate assets for ready, validation, processing,
> verification-required, retryable-provider-error, invalid/expired link, and
> success. Never show a password, raw email, token, OAuth code, provider
> payload, account-existence hint, or invented social provider.

## Prompt 2 — Progressive onboarding

Attach:

- `ONB-01-desktop-context.png` — `1-iZ5l-57RezRmFYyXcyY45jWiIFTF0um`
- `ONB-02-mobile-context.png` — `1ewm-HXQZv10tkfq3UNvly4JWHeIAFOWT`
- `SHELL-01-desktop-home.png` — `1JrHdP23rz27ECr2rVPDpRi_GSYMWaKEC`

Prompt:

> Create `ONB-01` as a three-step Clarity Grid learner-shell workflow at
> 1440x900 and 390x844. Step 1 has only Sales, Founder, Customer success, and
> Another context. Step 2 has only Learning goal. Step 3 has only optional
> Current situation and Minutes available each week. Include separate loading,
> save-processing, save-failed, revision-conflict, offline-unsaved,
> completed, and skipped states. Keep Back, Skip for now, Save & continue, and
> Finish profile reachable. Explain that answers do not trigger automated
> scoring or unreviewed course mapping. Do not add role, company, income,
> seniority, phone, persona, skill, recommendation, or marketing questions.

## Prompt 3 — Learner shell and home

Attach:

- `SHELL-01-desktop-home.png` — `1JrHdP23rz27ECr2rVPDpRi_GSYMWaKEC`
- `SHELL-02-mobile-home.png` — `12lQfy7L305LLoBw1VcLulz5gYxI9AM7t`
- `HOME-01-mobile-dashboard.png` — `1CgJ3XhYcclRxj2Zb6HRUXnH6pcQEcu01`

Prompt:

> Create `HOME-01` in the approved Clarity Grid shell at 1440x900 and 390x844.
> Active destinations are Home, My learning, Progress, and Settings only.
> Show a server-owned Continue learning card for Authority Closers Free Course,
> Module 1 progress as an honest 0..5 count, the next required activity, and a
> concise profile card. Create separate loading, no-active-enrollment,
> projection-unavailable, offline-stale, session-expired, and ready states.
> Missing data must say unavailable, not zero. Do not add library breadth,
> search, recommendations, streaks, leaderboards, fake cohorts, scores, or
> additional courses.

## Prompt 4 — Course and module path

Attach:

- `COURSE-01-desktop-overview.png` — `1sQs7ew-v1IO-Xb4h87dV_LOqFYRtloRk`
- `COURSE-02-mobile-outline.png` — `1vp7jaZ_LUl6Glm1NzljgFxIK8nB8rfs8`

Prompt:

> Create `COURSE-01`, `COURSE-02`, and `MOD-01` as source-matched Clarity Grid
> screens at 1440x900 and 390x844. Use the exact published course/module facts
> supplied by runtime or seed. Module 1 contains exactly Watch, Reflect,
> Implement, Review, Improve. Show available, current, in-progress, complete,
> and locked-with-reason states, pinned course version, and explicit free-course
> start/continue actions. Start occurs only from the explicit `Start free
course` action after exact recorded current consent and an active learner
> membership in the distinct public learner tenant satisfy
> `AC-FREE-SELF-ATTESTATION-v1`; show a safe fail-closed state for rejected
> inputs. `GAP-ENR-001` is superseded, but runtime proof is still pending. Do
> not fabricate Module 2-4 activities, broad catalog,
> certificate, quiz, score, reviewer, or content text.

## Prompt 5 — Activity workspace family

Attach:

- `PLAYER-01-desktop-player.png` — `1BASW-gVdQR8lWxDRfXN_svY5yqXkez-u`
- `ACT-02-mobile-reflection.png` — `1QMLN1QAlFDVnqlCG8JMWjG3OcEbo85ua`
- `ACT-03-desktop-implementation.png` — `1B03Slo9QX3c4vrE552cEtlqnDitVbnaO`
- `REVIEW-01-mobile-feedback.png` — `16HO9FeftBfm6uW334UWrAWYUyhC4YIwW`

Prompt:

> Create `ACT-01` through `ACT-05` inside one consistent Clarity Grid
> ActivityShell. Video shows player/caption/transcript/provider/evidence states
> and unique-coverage participation, never mastery. Reflection shows restored,
> dirty, saving, saved/revision, failed, offline-unsaved, and conflict states.
> Implementation separates instructions, acknowledgement, bounded text
> evidence, submit, and recorded/completed status. Review captures learner
> observation; Improve captures one explicit next action. Keep breadcrumb,
> module position, save/evidence state, primary action, and next action visible.
> Do not add media upload, external reviewer, AI feedback, score, mastery claim,
> or fabricated transcript/content.

## Prompt 6 — Factual progress

Attach:

- `PROG-01-desktop-progress.png` — `1HV9Ea2xn72e9s9pZ8UkAuc5bt4mVZ4yj`
- `SHELL-01-desktop-home.png` — `1JrHdP23rz27ECr2rVPDpRi_GSYMWaKEC`

Prompt:

> Create `PROG-01` as a source-bound Clarity Grid reference for the current
> implementation candidate, explicitly labeled `runtime_pending`. Show only
> canonical program,
> module, and activity states; Module 1 0..5 completion; current/next action;
> Modules 2-4 topology without invented activity breadth; and unavailable vs
> zero. Create loading, empty, ready, retryable-error,
> locked, and offline-stale states. Do not add skill scores, ranking, hidden
> composites, charts without real data, streak shame, analytics, certificates,
> or broad history.

## Prompt 7 — Profile, settings, and theme

Attach:

- `SHELL-01-desktop-home.png` — `1JrHdP23rz27ECr2rVPDpRi_GSYMWaKEC`
- `SHELL-02-mobile-home.png` — `12lQfy7L305LLoBw1VcLulz5gYxI9AM7t`
- `ONB-01-desktop-context.png` — `1-iZ5l-57RezRmFYyXcyY45jWiIFTF0um`

Prompt:

> Create `SET-01` through `SET-05` as source-bound Clarity Grid references for
> the current `runtime_pending`/`implementation_candidate` settings route at
> 1440x900 and 390x844. The current cards are Appearance, verified account,
> learning profile, and session; Profile edits route through the existing
> revisioned onboarding flow. Appearance is an accessible Light/Dark/System
> group and clearly states that the choice is device-local. Security adds no
> behavior beyond current sign-out and existing password/session recovery
> routes. Privacy may link only to existing Terms and Privacy pages; do not
> create a deletion or retention workflow. Produce
> matched Light and Dark assets using semantic roles; preserve Clarity Grid
> hierarchy and contrast. Do not invent final brand values, tenant branding,
> notifications, MFA, SSO/SCIM, integrations, billing, deletion, or provider
> behavior.

## Prompt 8 — Universal state family

Attach:

- `SHELL-01-desktop-home.png` — `1JrHdP23rz27ECr2rVPDpRi_GSYMWaKEC`
- `SHELL-02-mobile-home.png` — `12lQfy7L305LLoBw1VcLulz5gYxI9AM7t`

Prompt:

> Create `SYS-01` loading/processing, `SYS-02` retryable and terminal error,
> `SYS-03` offline, and `SYS-04` locked states in Clarity Grid at both reference
> viewports and both resolved themes. Every state explains what happened, what
> data/input is preserved, what is safe now, the next action, and support when
> terminal. Loading preserves structure. Offline labels cached data stale and
> blocks unsupported writes. Locked shows a safe prerequisite reason. Do not
> expose protected data, raw exceptions, provider details, tokens, or an
> indefinite generic spinner.

## Prompt 9 — Separate admin foundation

Attach:

- `ORG-01-desktop-overview.png` — `1x--v5pwj4GkCnhqodkSRZfIeLNxXaEjR`
- `ORG-02-desktop-people-assignment.png` — `1dTc6MsylnEvS0a_nIDR9PiL259QLpuF1`
- `AUTHOR-01-desktop-course-outline.png` — `1SNPUHW-TvhMb82bxqQh7zZMK9YmEi8yf`

Prompt:

> Create `ADM-01` through `ADM-06` as a separate Clarity Grid admin foundation,
> not a learner-shell skin. Include edge/app access boundary, selected tenant,
> role/permission, data freshness, truthful unknown metrics, read-first People,
> Catalog, and Learning Operations, plus named Correction and Grant commands
> with reason, consequence, cancel, processing, idempotency, and audit result.
> Create permission-denied, unavailable, empty, processing, retryable-error,
> and success states. Do not fabricate people, assignments, metrics, payments,
> scores, reports, reviewer queues, media, integrations, activity authoring, or
> cross-tenant resource existence.

## Implementation-agent prompt

> Implement only the screens/states assigned from `AC-WF-V01-ALPHA`. Read
> `ai-design-context.json`, `behavioral-spec.md`, and the matching
> `state-transition-matrix.csv` rows before changing code. Attach and match the
> exact Drive reference at the same viewport. Reuse existing routes, APIs,
> tokens, components, and real seed/runtime data. Treat `runtime_pending` as
> implemented-but-unproven, `implementation_candidate` as requiring bounded
> comparison/completion, and `gap_blocked` as an honest gated/reference state.
> Add
> unit/integration/a11y/responsive tests and exact implementation evidence.
> Never add future breadth, mock canonical data, client-authoritative access or
> progress, direct SQL recovery, secrets, or production claims.

## Visual QA prompt

> Compare the attached approved reference and implementation screenshot at the
> same viewport and state. Report only visible mismatches and behavioral-state
> contradictions: composition, hierarchy, crop, padding, margin, typography,
> border/radius, iconography, contrast, focus, disabled/locked meaning, save
> status, and responsive overflow. Rank by task impact. A screenshot cannot
> prove authorization, persistence, provider delivery, media evidence, or
> deployment; list those as runtime gates rather than visual passes.
