# Scope and authority

## User outcome

Give a learner a coherent, calm, mobile-first surface that answers “what is
my next safe action?” across discovery, learning, practice, evidence,
progress, planning, identity, settings, and recovery. The package is a
screen-family contract, not an implementation claim.

## In scope

- Dashboard/home and the shared desktop/mobile shell.
- My Learning and the public Discover/catalog experience.
- Program detail, enrolled learning path, module map, and prerequisite locks.
- Activity-owned Watch, Reflect, Implement, Review, and Improve states.
- Progress and descriptive insights with missing-versus-zero treatment.
- Today, week, and month plan views as bounded plan projections, not invented
  calendar commitments.
- Notifications and deep-link/read-state behavior.
- Course-completion certificate lifecycle and its distinction from competency
  certification.
- Login, registration, verification, recovery, OAuth callback, onboarding,
  session expiry, offline/stale, and retry states.
- Profile, private avatar selection/crop, and safe replacement semantics.
- Settings sections and Light/Dark/System theme mode with named preset, accent,
  density, and motion presentation variants.
- Full state matrix, accessibility/recovery criteria, and implementation handoff.

## Explicitly out of scope or gated

The package must not invent or activate:

- paid checkout, refunds, billing, entitlement, or commerce claims;
- access grants outside the controlled free-enrollment path;
- autonomous or official AI scoring, mastery, ranking, streaks, rewards, or
  competency certification;
- real-call recording, uploads, transcription, external AI processing, or
  provider data activation;
- a new media provider, caption/transcript asset, or playback guarantee;
- B2B manager views, organization membership operations, or tenant switching;
- live sessions, coach appointments, deadlines, reminders with schedule
  authority, or calendar commitments;
- analytics as canonical progress, access, payment, or completion state;
- account-level, cross-device, tenant, or learner/admin theme/appearance
  synchronization; named presets and accent, density, and motion remain
  browser-local presentation state only;
- any direct database or production VPS operation.

## Authority hierarchy used in this package

1. Current user instruction and explicit decisions.
2. Law, platform policy, security, privacy, accessibility, and engineering
   invariants.
3. Exact controlled Drive documents in the repository fetch order.
4. Current repository contracts and traceability records.
5. This package’s behavior and state matrix.
6. Visual references, only after behavior is fixed.

When two sources differ, the higher source wins and the conflict is recorded
as a decision or gap; a screen never resolves a business-policy ambiguity by
itself.

## Status vocabulary

| Status | Meaning |
| --- | --- |
| `spec_ready` | Contract can be handed to implementation without semantic invention. |
| `reference_ready` | Behavior and traceability are complete; visuals are still pending or reference-only. |
| `runtime_pending` | Existing implementation may exist, but this package has no exact-current runtime proof. |
| `gap_blocked` | A controlled capability gate blocks the affected capability only. |
| `production_approved` | Reserved for exact release, security, accessibility, and operational evidence; unused here. |

## Evidence boundary

The matrix uses `source_of_truth` to distinguish canonical server state,
device-local presentation state, authored content, and research hypotheses.
Analytics events are listed only as observation signals. They cannot create or
mutate access, completion, progress, payment, score, certificate, or
notification authority.
