# Behavioral specification

## Shared shell

Desktop retains a persistent learner rail for Dashboard, My Learning,
Discover, Progress, and Notifications, with Profile, Settings, and Help in the
lower account area. Mobile uses Home, Learning, Discover, Progress, and More.
The avatar/More surface exposes Profile, Notifications, Settings, Help, and
Sign out. A skip link, clear active label, visible focus, keyboard order,
safe-area padding, reduced-motion behavior, and a non-color state treatment
are required. Shell chrome stays visible during route-shaped loading.

No shell affordance hides a server authorization check. A deep link is an
intent, not access. The shell may display a signed-out or expired state without
disclosing protected resource existence.

## HOME-01 and plan horizons

`HOME-01` reads the current learner context, published catalog/enrollment, and
learning projection. It renders one dominant start/resume/continue action and
does not duplicate the same program as competing cards. `PLAN-01..03` are
Today/Week/Month subviews of the home planning area. They consume only a
canonical plan/calendar projection or explicitly learner-authored intent. If
the projection is absent, the surface says “planning unavailable” or “no saved
plan” rather than inventing dates, durations, reminders, appointments, or
deadlines. Missing plan data is not zero progress.

The authenticated learner may see the explicit `Start free course` action only
where the approved free-enrollment policy makes it eligible. The client does
not provide person or tenant identity and the action itself does not prove
access until the server returns its canonical result.

## LEARN-01, DISC-01, COURSE-01, COURSE-02, MOD-01

`LEARN-01` separates in-progress, saved, and completed views using canonical
projections. `DISC-01` and `COURSE-01` are read-only catalog/preview surfaces;
the preview preserves a return intent through auth but never enrolls. `COURSE-02`
is an enrolled program detail view bound to a published version. `MOD-01`
renders configured activity order and exact safe lock reasons. Program-specific
sequential prerequisites do not become global platform semantics.

## Activity loop and MEDIA-01

Each activity renderer shares the same lifecycle: load → inspect eligibility →
perform the activity → save/submit evidence as configured → receive a named
server result → continue or return. Watch, Reflect, Implement, Review, and
Improve are stable IDs and may reuse an activity shell. Controls should favor
authored choice, ordering, matching, branching, evidence-chip, or confidence
interactions where the controlled activity schema permits; this is a low-typing
interaction direction, not a score model.

`MEDIA-01` is activity-owned. It exposes accessible play/pause/seek, caption,
transcript, resume, and provider-error affordances only after the media port
and assets are approved. Watched coverage is versioned, server-authoritative
unique instructional intervals. The provisional 90% operating default is
participation evidence, not mastery. Buffering, page open, current time,
analytics, or a client “complete” flag cannot complete the activity.

Reflection/draft writes use a revision precondition and logical idempotency.
Supported drafts survive safe expiry and offline transitions. Implement
evidence records what the learner says or selects; it does not assert that an
offline real-world action occurred. Review/Improve do not fabricate coach,
AI, or official results.

## PROG-01 and INSIGHT-01

`PROG-01` shows canonical course/module/activity completion, lock reasons,
and an explicit missing/unavailable state. `INSIGHT-01` may show descriptive
analytics/read-model summaries with labels for stale, partial, or unavailable
data. It must not display a made-up mastery score, rank, streak, reward,
leaderboard, or official result. A chart has a text equivalent and distinguishes
unknown from zero.

## NOTIF-01

Rows expose a safe title, date/time only when canonical notification data has
one, read/unread state, and an owned deep-link target. Marking a row read is a
separate idempotent read-state mutation. Delivery preferences and marketing
consent are not inferred from reading a notification. If a target is no longer
available, explain it without exposing protected details and keep global
navigation available.

## PROF-01 and AVATAR-01

`PROF-01` shows self-scoped identity facts and context attributes; role,
membership, or tenant semantics are not inferred from display text. `AVATAR-01`
first creates a local preview/crop, validates file type/size/dimensions, then
submits only through an approved profile service. While processing, preserve
the current avatar and label the pending state. On success, the new object
revision becomes current and the old object is superseded under the retention
policy. On failure, preserve the prior avatar and allow retry/cancel. No
provider or upload activation is claimed by this package.

## SET-01..05 and theme variants

`SET-01` reads verified account facts; `SET-03` links to onboarding rather than
duplicating its fields; `SET-04` exposes only approved recovery, policy, help,
and deletion-request entry points; `SET-05` reads current session facts and
offers same-origin sign-out. Sensitive commands require recent authentication
and explicit confirmation where their controlled contract requires it.

`SET-02` provides Light, Dark, and System. Light is the product default; Dark
is an explicit local variant; System follows `prefers-color-scheme`. The
preference is best-effort browser state, not an account, tenant, consent,
notification, access, progress, or branding fact. Storage failure falls back to
System/current-page rendering without blocking learning.

## Auth, onboarding, expiry, and offline

Auth inputs have labels, associated validation, password-manager/paste support,
and safe preservation. Register consent is exact-version-bound; responses are
existence-neutral. OAuth callback results are provider-independent and never
show tokens or payloads. Reset revokes active sessions according to the
controlled contract.

`ONB-01` uses bounded fields, explicit steps, save/revision status, and safe
resume. It never infers access, role, score, or course enrollment.

`AUTH-07` names the expired session, explains what is preserved, offers
reauthentication, and returns to the exact route/step. `SYS-03` explains that
offline is a connectivity boundary; it may render an allowlisted stale read or
local draft but never asserts protected authority. Cache/draft cleanup on sign
out, identity change, expiry, tamper, or authorization loss is explicit.

## Certificates

`CERT-01` distinguishes `incomplete`, `processing`, `issued`, `not_found`, and
`permission_denied`. The artifact is shown only when the canonical completion
predicate and issuance rule authorize it. A course-completion certificate is
not a competency certification, official skill credential, mastery statement,
or score.
