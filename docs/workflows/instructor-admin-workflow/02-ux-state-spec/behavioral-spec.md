# UX/UI behavioral specification

This specification binds stable screen IDs to structure, actions, states and
recovery. It is intentionally implementation-neutral. Action labels are
recommendations only where the controlled sources do not define copy.

## Shared AC Admin shell

`UI-C001 AppShell`, `UI-C004 SideNav`, `UI-C005 Breadcrumbs`,
`UI-C006 PageHeader`, `UI-C014 StatusBadge`, `UI-C024 Toast`,
`UI-C025 InlineAlert`, `UI-C027 Skeleton`, `UI-C065 ErrorBoundary` and
`UI-C066 OfflineBanner` form the shell contract. The shell should provide:

- a persistent product/surface label (`AC Admin`), current section and
  breadcrumb; “Instructor Studio” is a label over Catalog/Review, not proof of
  a new role;
- a keyboard-accessible skip target, predictable focus on route changes and
  a visible session/context indicator without sensitive details;
- explicit loading, empty, stale, denied, retryable and terminal states;
- a navigation item only when the server-provided capability permits it, with
  a blocked informational entry when a known capability is intentionally
  gated; the client never decides authorization;
- a non-color status treatment, reduced-motion-safe transitions and target
  sizes of at least 44pt/48dp according to the relevant platform guidance.

## `ADM-OVERVIEW` — `/admin`

**Structure:** page header with scope/freshness; a small set of source-backed
operational links; capability-gate notices; recent audit/recovery references
only when returned by an authorized read model. Do not insert learner counts,
revenue, score averages or provider success values.

**Primary action:** open the next authorized module (`design inference`).
**Secondary:** retry a failed read; inspect a returned reference. **States:**
`loading`, `ready`, `empty`, `offline_or_stale`, `permission_denied`,
`retryable_error`, `terminal_error`. **Recovery:** retry with correlation
reference; escalate to Technical Administrator when the read model is stale.

## `ADM-USERS` — `/admin/users`

**Structure:** page header; `UI-C039 SearchField`; filter summary; `UI-C041
DataTable` on wide screens; stacked person records on compact screens;
pagination and an explicit freshness indicator. No invented counts or payment
columns. **Primary:** open a person (`design inference`). **Secondary:** clear
filter or retry. **States:** `loading`, `ready`, `empty`, `offline_or_stale`,
`permission_denied`, `retryable_error`, `partial`. **Recovery:** preserve
search/filter input; for mixed results show per-item status and the next safe
support path. Bulk behavior is `BLK-11`.

## `ADM-USER-DETAIL` — `/admin/users/{person}`

**Structure:** identity header with non-sensitive context; enrollment/content
version panel; progress/evidence timeline; support/audit reference panel;
explicit current-vs-historical markers. Never present analytics as canonical
progress. **Primary:** inspect the source-backed detail (`design inference`).
**Secondary:** open a support/audit reference where authorized. **States:**
`loading`, `ready`, `empty`, `permission_denied`, `session_expired`,
`offline_or_stale`, `reconciliation_required`, `support_required`,
`terminal_error`. **Recovery:** preserve route context; re-authenticate and
revalidate; hold and reconcile inconsistent state; escalate rather than edit
DB. Any correction must use a confirmation panel, reason and superseding
audit event.

## `INS-PROGRAMS` — `/admin/programs`

**Structure:** page header; program search/filter; wide `DataTable` or compact
stacked records; status/version badges; permitted “open content” affordance.
**Primary:** open a Program (`design inference`). **Secondary:** create draft
only if the server grants the catalog capability; otherwise show denied.
**States:** `loading`, `ready`, `empty`, `draft`, `permission_denied`,
`offline_or_stale`, `retryable_error`, `terminal_error`. **Recovery:** preserve
query and draft intent; a failed create/save returns `retryable_error` and never
shows a published result.

## `INS-CONTENT` — `/admin/programs/{program}/content`

**Structure (wide):** page header with Program and version; left
Program/Module/Activity tree; center editor or dependency summary; right
validation/version/audit panel. **Structure (compact):** `UI-C044 Stepper`
for tree → editor → validation → version result; no horizontal table.

**Primary:** save a draft (`design inference`, server-authorized). **Secondary:**
validate dependencies; request review/publish only if rendered by server
capability. **States:** `loading`, `ready`, `draft`, `validation_error`,
`in_review`, `version_conflict`, `permission_denied`, `session_expired`,
`offline_or_stale`, `retryable_error`, `terminal_error`,
`assessment_authoring_blocked`, `provider_failed`. **Recovery:** preserve
unsaved input; show exact dependency and version references; create a new
superseding draft after conflict; do not silently mutate a published version.

## `INS-PUBLISH` — same content route, publish/version context

**Structure:** `UI-C044 Stepper` or `UI-C064 ConfirmationPanel` showing target
version, validation summary, dependencies, impact statement and required
reason/confirmation where the contract demands it. The panel must not invent
audience, eligibility, approval owner or billing effects.

**Primary:** submit the server-backed version action (`design inference`).
**Secondary:** return to draft; open validation details. **States:**
`validation_error`, `in_review`, `version_conflict`, `permission_denied`,
`reconciliation_required`, `success`, `retryable_error`, `terminal_error`.
**Recovery:** retain the draft and version id; reconcile before retry; show
returned audit/reference id; published content remains immutable.

## `ADM-PROGRESS` — `/admin/progress` (candidate)

**Structure:** diagnostics header with explicit scope/freshness; filters;
stuck/inconsistent records; canonical state and recovery owner; no
unregistered actions. **Primary:** inspect a returned diagnostic (`design
 inference`). **Secondary:** retry/reconcile only if the API grants it. **States:**
`blocked`, `loading`, `ready`, `empty`, `permission_denied`,
`reconciliation_required`, `support_required`, `retryable_error`.
**Recovery:** candidate route first resolves the route/authz contract; until
then the UI remains `blocked` and links to `BLK-09`.

## `ADM-AUDIT` — `/admin/audit` (candidate)

**Structure:** restricted `UI-C062 AuditTimeline`; actor/tenant/resource/action
context; reason; before/after or supersession references; trace/job/provider
correlation; masking and export affordances only when server grants them.
**Primary:** inspect a trace (`design inference`). **Secondary:** return to
source object. **States:** `blocked`, `loading`, `ready`, `empty`,
`permission_denied`, `offline_or_stale`, `retryable_error`, `terminal_error`.
**Recovery:** route, masking and export contract must be approved before
implementation (`BLK-09`, `BLK-12`).

## `ADM-ASSESS-REVIEW` — blocked review surface

Show an explicit `assessment_authoring_blocked`/`blocked` panel with the
missing contract: question schema, rubric/attempt policy version, approval
ownership and route authorization. Do not render fake score fields or an AI
“publish” button. The controlled assessment boundary is human-confirmed
official evidence; AC-SVAL gates are a release prerequisite.

## `ADM-MEDIA` — blocked media surface

The future surface would use `UI-C037 FileUpload`, `UI-C038 Dropzone`,
`UI-C055 CallUploadStatus` only where appropriate and a provider-neutral
lifecycle. Until provider/retention/limits/route decisions are approved, show
`blocked`; course content may retain an expected media dependency in draft.
Real-call processing is separately blocked by `BLK-06`.

## `ADM-HEALTH` and `ADM-SUPPORT-VIEWAS` — blocked surfaces

System health and view-as are not registered routes in the controlled IA. Do
not expose them. The architecture records future state names and recovery
expectations only: provider/job/read-model diagnosis must be scoped and
audited; view-as, if ever approved, is read-only by default, clearly bannered
and time-limited, with exact duration/masking still `BLK-12`.

## Telemetry boundary

The `analytics_event` field in the CSV is a descriptive event proposal only.
Canonical state changes come from domain facts/outbox/audit records. Events
must not grant access, mark progress, create a score or stand in for a
publication result. If implementation names differ, update the matrix and
manifests together.
