# Report and prospect follow-through

The owner's 24 September feedback adds the following acceptance requirements.
This is a tracked delivery scope, not evidence that these capabilities are live.
The last explicit release ordering remains verified core first, followed by
prospect journeys. Fixing the saved-call failure and proving useful new report
output precede widening the CRM surface.

## Core acceptance

- A saved recording with a quoted plan must render its supported plan revision.
  Unknown versions still fail closed. Retry must retain the call and cannot
  silently approve another paid request or discard previous work.
- Status, actionable error, and the primary recovery action must be visible in
  the normal workflow at desktop, short laptop and narrow mobile viewports.
  A sticky region must not hide content or create nested scroll traps. Long
  report content may scroll; fitting an entire report into one viewport is not
  a goal.
- The complete saved report has a continuous reading mode and a tabbed mode.
  Both use the same accepted report, evidence and audio controller. Skills,
  moments, next actions and transcript stay reachable and readable. Dialogs and
  buttons must support keyboard focus, mobile touch, zoom and reduced motion.
- Assess the new single-call output against its transcript and the prior output:
  clear explanation where useful, specific coaching, grounded moments,
  accessible language, faithful quotations and actionable next steps. Counts,
  longer prose and passing fixtures alone do not prove quality. Preserve the
  old result and record model, prompt pack, settings, costs and source revisions
  for each comparison. Do not label the bounded single-call release as all of
  Brain 3 or as adjudicated scoring.

## Following milestone: persistent prospect journeys

- Canonical owner-scoped prospect, business and product/project context;
  exportable records linked to the same AC account, with tenant and role checks.
- Explicit call-to-prospect links with corrections and an audit history; inferred
  candidates need confirmation before merging people or business records.
- Call purpose such as discovery, follow-up and closing, retaining its source,
  uncertainty and user correction. A prospect's linked call history must show
  chronology, count, next action and source recording/report.
- Effort summaries distinguish measured call duration and recorded activities
  from unknown work. Compare a salesperson's observations across leads without
  inventing effort, attribution, conversion impact or performance scores.
- Hot/cold or readiness labels require defined owner-approved semantics,
  supporting evidence, recency and uncertainty. They are not facts extracted
  merely from vocal tone. Official evaluation remains gated by AC-SVAL.
- Saved Calls and prospect screens should behave as a usable working library:
  clear names, useful filters, accessible navigation and linked details; do not
  ship decorative tabs that have no functioning underlying capability.

## Validation boundary

Use controlled documentation for the data/API/security contract before the new
persistent slice. Founder images supply design intent, not missing business
semantics. No prospect data model, automated label, export permission, paid
request or production change is activated by this scope record.

## Added owner requirements: batches, settings and expert guidance

The owner subsequently made these explicit delivery requirements. They are not
implemented merely by listing them here, and do not replace the urgent core
release acceptance above.

- Multiple recording selection in one workflow, with an editable chronological
  order and per-call date/type/prospect context. Show the whole ordered queue and
  each item's actual outcome; process sequentially, retain successful outputs,
  and recover failed items without silently resubmitting completed work.
- Reuse verified-account/profile admission, per-file validation, source consent,
  plan quotes, idempotency, account allowance and provider budget controls. A
  batch must not multiply free allowance, hide its aggregate commitment or
  bypass existing recording limits. Use small fictional clips for deterministic
  and failure-recovery tests; paid tests remain within explicit authorization.
- Shared AC profile and an understandable settings surface for supported account,
  report-language, appearance and processing preferences. Separate personal
  preferences from authorized administrator controls. Expose only implemented
  settings and show failures honestly.
- A future coach audio/video library, supplied later by the owner: versioned
  source records, access/retention/provenance, ingestion state, validated timed
  transcripts, topic/skill metadata and timestamped excerpts. Retrieval must
  return authorized source ranges and explain their relevance to an observed
  report issue, without inventing a quotation or claiming the coach reviewed
  the seller's call.
- Reuse those evidence-linked recommendations in both report modes and preserve
  the seller-call audio position when opening coach media. Missing sources,
  low-confidence matches, revoked access and unavailable media have explicit
  states. No fabricated demonstration recommendation may appear as live advice.

The initial library architecture does not authorize ingesting unspecified Drive
folders or running transcription before the recordings, permissions and cost
controls are supplied. It also does not authorize replacing working engines
with speculative C++ components without equivalence and performance evidence.
