# End-to-end journeys


These journeys describe future workflow architecture, not implemented
features. Each journey stops at a source-backed boundary and points to a
state in the machine-readable matrix.

## J-01 — Author and version a course

**Actor:** Content Manager (canonical role; any “Instructor Studio” label is
subject to `BLK-01`). **Entry:** `/admin/programs`.

1. The operator opens the catalog and locates a Program. The list can be
   loading, empty, stale/offline or permission denied; no counts are invented.
2. The operator opens `/admin/programs/{program}/content` and sees the
   Program → Module → Activity tree plus version/status context.
3. The operator edits or prepares a draft Program/Module/Activity version. A
   draft preserves input locally or server-side according to the eventual
   contract; this package never promises offline sync.
4. The operator validates required dependencies, including media references
   and prerequisite-cycle checks. A cycle or missing dependency blocks
   publication and leaves the draft intact.
5. The operator requests review or publication only through an authorized
   server action. Exact approval separation is `BLK-01`/`BLK-07`.
6. The system records the lifecycle `DRAFT → IN_REVIEW → PUBLISHED → RETIRED`.
   A published version is immutable; a material correction creates a new
   version and historical learner evidence remains pinned.
7. On conflict, expiry, provider failure or reconciliation, the system shows
   the durable state and a recovery path; it does not claim success from a
   click or analytics event.

**Exit:** a source-backed draft/review/publish result, or an explicit blocked
state with escalation. No audience, billing or B2B publication policy is
assumed.

## J-02 — Inspect enrollment and progress safely

**Actor:** Business Administrator, Support Agent, Auditor or other existing
Admin role with server-granted permission. **Entry:** `/admin/users`.

1. Search/list loading and empty states are explicit. The operator opens a
   person at `/admin/users/{person}`.
2. The detail view shows canonical enrollment, content version, progress and
   evidence context only when authorized. Analytics is not substituted for
   canonical state.
3. If state is stuck or inconsistent, the operator records a case/reference,
   sees the owning recovery layer and uses a safe retry/reconciliation path if
   granted. Direct database edits are forbidden.
4. A sensitive correction requires explicit authorization, a reason and an
   append-only/superseding audit record. The original history remains visible.
5. If access is denied, the operator sees a non-leaking denial and escalation
   instruction. If the session expires, unsaved local input is handled by the
   route/session contract rather than silently discarded.

**Exit:** inspect-only completion, a source-backed recovery action, or a
support escalation. Learner counts and entitlement semantics remain blocked.

## J-03 — Assessment authoring and human review gate

**Actor:** Content Manager and Coach / Reviewer, with any approval separation
resolved later. **Entry:** content route; review queue route is blocked.

1. The content operator opens an Activity version and sees the assessment
   capability boundary, evidence/rubric version references and current
   lifecycle.
2. If required assessment schema, rubric, attempt policy or approval owner is
   missing, the editor remains in `assessment_authoring_blocked` and links to
   `BLK-07`; it must not fabricate fields.
3. A Coach / Reviewer may review a permitted submission through the future
   review surface. Official results remain human-confirmed; original score and
   evidence are preserved when a reasoned override or appeal occurs.
4. AI extraction/feedback may be considered only behind AC-SVAL gates; no
   official AI action is exposed here.

**Exit:** draft/reference handoff or explicit blocked gate. No score values or
   attempt limits are shown by this package.

## J-04 — Attach course media through the provider gate

**Actor:** Content Manager or other explicitly authorized operator. **Entry:**
content route; dedicated media route is blocked.

1. The editor associates an expected media dependency with an Activity.
2. Dropzone/file-upload feedback checks known client-safe constraints only
   when the eventual contract supplies them; provider-specific limits are
   `BLK-08`.
3. The platform lifecycle is visible as `EXPECTED → UPLOADING → PROCESSING →
   READY | FAILED → RETIRED`. Retry is idempotent and cannot imply readiness.
4. Provider timeouts/failures isolate the capability, preserve draft input and
   offer retry/escalation. Raw provider keys never appear in the UI.
5. Real-call recording, transcription and external AI processing stop at the
   P0 governance gate (`BLK-06`); this journey covers course media only.

**Exit:** media dependency ready/failed with durable status, never an
unverified “published” result.

## J-05 — Audit and recover without rewriting history

**Actor:** Technical Administrator, Support Agent, Auditor or authorized
operator. **Entry:** `/admin/audit` is an explicit candidate; exact route is
subject to `BLK-09`.

1. The operator filters a restricted audit timeline by actor, tenant/context,
   target, reason and trace/reference. Masking and export permissions follow
   the server contract.
2. A recovery event is correlated to the canonical object, outbox/job and
   provider state where applicable. Analytics read models are explanatory only.
3. Restore/replay enters a hold/reconcile state before external effects. Job
   replay and retries are idempotent; duplicate actions do not create duplicate
   entitlements, evidence or audit records.
4. View-as, if approved later, must be scoped, read-only by default, clearly
   bannered and audited. Duration and masking rules are `BLK-12`.
5. The operator escalates at the correct recovery layer (self, support,
   domain, technical, policy). No workflow instructs a raw DB edit.

**Exit:** reconciled state with evidence or a named escalation; never silent
history replacement.
