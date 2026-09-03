# State taxonomy

State names below are stable package identifiers. They describe what the
surface must communicate; they do not authorize a backend transition. A
server response and the canonical domain remain authoritative.

| State | Meaning | Required presentation | Safe recovery |
| --- | --- | --- | --- |
| `loading` | First fetch or route transition has not completed | Named loading status and stable skeleton; preserve route context | Wait; allow cancel/back when safe |
| `ready` | Source-backed data is available for this actor/context | Data plus version/freshness context where relevant | Continue within authorized actions |
| `empty` | The query is valid but has no records | Explain the empty condition without fake counts; provide scoped next action | Change filter or create a permitted draft |
| `permission_denied` | Server denied actor/context/resource/action | Non-leaking denial with support/reference path | Request correct access or escalate |
| `session_expired` | Auth/session can no longer authorize the action | Preserve non-sensitive input and explain re-authentication | Re-authenticate; revalidate before retry |
| `offline_or_stale` | Network unavailable or read model is stale | Persistent stale/offline banner and last-known timestamp if supplied | Retry; do not claim mutation synced |
| `retryable_error` | Temporary request/job failure | Inline error with correlation/reference and retry | Idempotent retry or escalation |
| `terminal_error` | Request cannot complete under current contract/data | Explain blocked condition without provider secrets | Correct source data or escalate |
| `draft` | Editable content/version is not published | Draft badge, version identity and unsaved/saved status | Save, discard only with confirmation, or continue editing |
| `validation_error` | Required contract/dependency check failed | Field/section errors and summary; preserve all input | Fix indicated fields/dependencies |
| `in_review` | Version has entered a controlled review state | Review badge, immutable version identity and next owner only if supplied | Follow approved review path; do not bypass |
| `version_conflict` | Submitted version is older than current source | Conflict explanation and both version references where safe | Reload/compare and create a new superseding draft |
| `success` | Server confirmed the requested action | Result, audit/reference id if returned and next safe action | Continue or inspect history |
| `partial` | A bounded multi-item operation has mixed outcomes | Per-item result and retryable failures; never imply all succeeded | Retry only failed items if contract allows; otherwise escalate |
| `reconciliation_required` | Canonical state and side effect/read model disagree | Hold banner; show affected capability and recovery owner | Reconcile through job/support path; no direct DB edit |
| `provider_failed` | External provider adapter failed or timed out | Provider-neutral failure and preserved draft/input | Retry with idempotency or use approved fallback if one exists |
| `processing` | Accepted work is asynchronous and not ready | Named processing status and poll/reload affordance | Wait or retry according to job contract |
| `uploaded` | Upload accepted by platform but readiness is not proven | Uploaded/awaiting processing status; no publish implication | Continue only where dependency permits; inspect status |
| `upload_failed` | Media upload did not complete or was rejected | Failure reason safe to disclose and retry affordance | Retry idempotently or replace draft reference |
| `assessment_authoring_blocked` | Assessment behavior lacks a controlled schema/gate | Explain missing contract and link to blocked decision | Keep reference draft; do not invent fields or scores |
| `support_required` | Operator cannot safely resolve within their boundary | Case/reference path, owning layer and handoff context | Open/escalate support case |
| `blocked` | Capability is explicitly outside the package or gated | Clear blocked label and smallest next authority | Stop; resolve source/policy/release gate |

## Cross-cutting state rules

- Status must be conveyed by text and structure as well as color. Use an icon
  only as a supplement, never as the only signal.
- Async outcomes must be announced to assistive technology and remain visible
  until the user can understand the result. Toasts cannot be the only record.
- Any mutation rechecks actor, tenant/context, resource and action on the
  server. A visible button is not evidence of authorization.
- A retry is idempotent and does not create duplicate content, evidence,
  entitlement, audit history or provider side effects.
- Sensitive operations require a reason and an append-only/superseding audit
  record. The original audit-critical value is never overwritten.
- Offline/stale presentation never implies that a mutation was synchronized.
- When a P0 gate blocks a capability, unrelated navigation remains usable and
  the state identifies the blocked capability rather than blanking the app.
