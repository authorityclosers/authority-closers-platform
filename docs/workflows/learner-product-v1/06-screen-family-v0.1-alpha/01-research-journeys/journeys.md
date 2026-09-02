# Learner journeys and recovery paths

## JRN-LSF-01 — From identity to first safe value

`AUTH-01`/`AUTH-02` → `AUTH-03` or `AUTH-06` → `ONB-01` (optional, resumable)
→ `HOME-01` → explicit in-app `Start free course` where the controlled policy
allows it → `COURSE-02` → `MOD-01` → `ACT-01`.

The first-value hypothesis is a measurable product experiment, not a promise:
the learner should reach meaningful value quickly (the controlled slice uses a
roughly 15-minute target). Onboarding failure or recommendation unavailability
must not silently grant/revoke access or block neutral learning access.

Recovery branches: invalid credentials preserve safe fields; provider failure
returns to a bounded retry; an expired session returns to `AUTH-07` and then
the intended route; offline shows `SYS-03`; every mutation names its canonical
result before a learner can repeat it.

## JRN-LSF-02 — Discover, preview, and start

`DISC-01` → `COURSE-01` → sign in/return path → `HOME-01` explicit start →
`LEARN-01`/`COURSE-02`.

The public preview is read-only. Access/enrollment can occur only from the
authenticated learner surface through the approved free-enrollment command.
Paid commerce and entitlement are future-gated and must not appear as a
successful state in this package. Empty, partial, and catalog-provider failure
states leave the learner with a safe browse or retry action.

## JRN-LSF-03 — Resume a program and module path

`HOME-01` or `LEARN-01` → `COURSE-02` → `MOD-01` → activity row → `ACT-01..05`
→ module/progress projection.

The program’s published version and configured prerequisite rules control
eligibility. A locked module or activity explains only the safe prerequisite
reason and permitted next action; it does not expose unauthorized content.
Modules may be sequential for this configured program without converting the
platform into a globally sequential LMS.

## JRN-LSF-04 — Complete the activity loop

`ACT-01` Watch → `ACT-02` Reflect → `ACT-03` Implement → `ACT-04` Review →
`ACT-05` Improve → `PROG-01`/`MOD-01`.

Watch completion uses versioned, server-authoritative unique watched intervals
and a provisional 90% instructional coverage default where that policy is
actually configured. Playback position, page open, analytics, or buffering do
not alone complete an activity. Reflection and evidence drafts preserve safe
input through save, retry, expiry, and supported offline behavior. Low-typing
click-first controls are an interaction direction, not a scoring model.

## JRN-LSF-05 — Plan horizon and next action

`HOME-01` → `PLAN-01` Today, `PLAN-02` Week, or `PLAN-03` Month → selected
owned/eligible item → `LEARN-01`/`ACT-*`.

Plan horizons are read-only projections of a canonical plan/calendar source
when that source is available, or learner-authored intent where explicitly
supported. They must not invent due dates, live appointments, coaching
commitments, notification delivery, cadence, or schedule authority. “No plan”
and “planning data unavailable” are separate states; neither means zero
learning progress.

## JRN-LSF-06 — Progress, insight, and certificate

`PROG-01` → `INSIGHT-01` → module/activity detail → completion predicate →
`CERT-01` when the controlled completion rule issues an artifact.

Progress shows canonical course/module/activity completion and explicit lock
reasons. Descriptive analytics may explain behavior or surface a stale/missing
panel but never changes canonical state. A certificate is a course-completion
artifact only; it is not a competency, mastery, or official skill credential.

## JRN-LSF-07 — Identity, avatar, settings, and theme

Avatar/More → `PROF-01` → `AVATAR-01` or `SET-01..05`. Profile edits remain
self-scoped. Avatar selection has a local preview, validation, processing,
success, and supersession path; upload/provider activation is not claimed.
`SET-02` applies Light/Dark/System best-effort on the current browser. Theme
storage or device preference cannot alter access, tenant, consent, progress,
notifications, or session authority.

## JRN-LSF-08 — Notification deep link

Header bell/More → `NOTIF-01` → read/open → an owned route. Read state and
delivery preferences are separate from learning facts and commercial consent.
If notifications are not available or partially loaded, the learner sees the
scope boundary and can retry or continue via global navigation.

## JRN-LSF-09 — Failure and recovery loop

Any route → `SYS-01` loading → ready, `SYS-02` retryable/terminal, `SYS-03`
offline/stale, `AUTH-07` expiry, or `SYS-04` locked/permission denied.

The three-layer model is mandatory: presentation state (what the UI can render),
canonical domain state (what the server says happened), and recovery ownership
(what the learner/support/operator may safely do). A generic spinner, partial
card, stale cache, or analytics event may not stand in for a durable pending,
reconciliation, evidence-processing, or completion state.
