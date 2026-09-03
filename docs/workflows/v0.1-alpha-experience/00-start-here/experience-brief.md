# Experience brief

## Product and outcome

Authority Closers v0.1 Alpha is a browser-first learner LMS foundation with a
separate admin/control-plane foundation. Its first learner value is not passive
video consumption: a verified learner reaches a published free course, sees an
honest version-pinned path, and completes the Module 1 learning loop through
watch evidence, private reflection, implementation evidence, review, and one
explicit improvement action.

Workstream outcome: one source-backed behavioral and visual contract that can
drive implementation, visual generation, QA, and release evidence without
expanding into the future LMS.

## Audience and actor boundary

| Actor             | Goal in this slice                                                                            | Boundary                                                                               |
| ----------------- | --------------------------------------------------------------------------------------------- | -------------------------------------------------------------------------------------- |
| Anonymous visitor | understand the free course and create/recover an account                                      | no protected learner data                                                              |
| Unverified person | verify the exact account safely                                                               | no learner session before verification                                                 |
| Verified learner  | give optional bounded context, explicitly start the free course, learn, save work, and resume | active learner membership in the distinct public learner tenant; self-scoped data only |
| AC owner/admin    | diagnose and perform named, authorized operations                                             | separate admin host/app, tenant and permission checks, audited commands                |
| Support/operator  | understand recoverable states without raw database intervention                               | least privilege; view-as is read-only by default and audited when activated            |

One canonical person may have memberships in more than one organization. A
role or experience answer must not create a duplicate identity.

## Entry, first value, and exit

- Entry: public free-course detail, `/register`, `/login`, or a safe deep link.
- Account-ready milestone: verified active identity with a host-only session.
- First-value target: roughly fifteen minutes to useful, methodology-grounded
  action, treated as an experiment rather than a scientific guarantee.
- Slice exit: Module 1 required activities have authoritative completion
  evidence and the next state is explained. Modules 2-4 may remain visibly
  locked/unavailable; the UI must not invent their content or completion.

## Platforms

- Windows: current Microsoft Edge-compatible web and installable PWA behavior.
- iOS: Safari web and Home Screen/standalone PWA behavior with safe-area-aware
  layout.
- Compact reference viewport: 390 CSS px wide.
- Wide reference viewport: 1440 CSS px wide, with readable learning content
  constrained inside the shell.
- Native Windows and native iOS applications are extension contracts only.

## Authority order

1. Explicit current user decisions in this task.
2. Ratified product, legal, security, accessibility, and engineering rules.
3. Exact controlled Drive sources in the required order.
4. Repository route/screen, authorization, email, and UI traceability
   contracts.
5. This package's behavioral spec and state matrix.
6. Approved Clarity Grid visual references.

A visual reference never authorizes a route, business state, field, provider,
or admin action. If behavior and pixels disagree, behavior wins and the visual
must be revised.

## Current user decisions applied

- Deliver one connected experience from auth through onboarding and Module 1.
- Include profile/settings and a global Light/Dark/System appearance control.
- Use the approved Clarity Grid direction and the supplied Drive images.
- Make failure, recovery, offline, locked, and session-expired behavior visible.
- Keep learner and admin foundations separate.
- Apply ADR 0028: only the explicit free-course start action may convert the
  exact recorded current consent into `AC-FREE-SELF-ATTESTATION-v1`, and only
  for an active learner membership in the distinct active public learner
  tenant.

The theme decision is interpreted narrowly: it changes semantic presentation
tokens across the current surface. It does not authorize tenant branding,
white-labeling, custom typography, custom palettes, or a new preference API.
The current device-local implementation is an implementation candidate; this
package does not claim cross-device synchronization or live runtime proof.

## Experience principles

1. Answer continuously: Where am I? What is required? Is my work saved? What
   is complete or locked? What happens next? How do I recover?
2. Keep canonical facts server-owned. Analytics, UI optimism, and visual state
   do not become progress, access, or evidence authority.
3. Preserve learner work through retry, revision conflict, navigation, and
   session expiry as far as the approved storage contract permits.
4. Make missing data visibly different from zero and provider delay different
   from completion.
5. Use calm, directional learner composition and dense, auditable admin
   composition without sharing the same trust boundary.
6. Treat accessibility and responsive recovery as component behavior, not a
   screenshot polish pass.

## Non-goals

No billing, checkout, refunds, broad commerce, quizzes, autonomous official
scoring, call uploads/review, simulator, community, calendar, inbox, broad
library/search, recommendations, SSO/SCIM, tenant branding, native app-store
release, broad analytics, broad B2B, or full course authoring is designed as an
active v0.1 capability here.

## Handoff definition

This package is complete when its JSON and CSV parse, stable IDs agree, every
primary action has a system response and recovery, source and inference are
separated, all extension boundaries remain explicit, and QA can distinguish a
reference-ready screen family from a production-approved runtime.
