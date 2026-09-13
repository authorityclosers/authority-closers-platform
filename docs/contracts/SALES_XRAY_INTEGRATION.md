# Sales Xray integration contract

2026-09-13. Follow-on to the current AC release. The coordinator owns this
isolated change; Release Recovery owns integration, image publication and rollout.
This document describes implemented routes, not permission to activate processing.

## Client entry points

| Client | Owned addition | Integration needed |
| --- | --- | --- |
| Standalone | `apps/sales-xray-web`, upload/report screen with evidence moments, saved sound measurements and report printing | Separate server image and exact host/API/auth routing |
| LMS | New `apps/learner-web/app/sales-xray/page.tsx` and `layout.tsx` | UI owner adds the Practice/navigation entry using current session/layout conventions |
| Admin | New `apps/admin-web/app/sales-xray/` | UI owner adds its admin navigation entry; backend rechecks verified control account and current admin permission |
| Free course / website | Reusable shared client and server API | Distinct entry buttons and entitlement policy remain to integrate; no invented minute grants |

The new learner route imports the shared CallStudio and scoped stylesheet. No
existing learner, admin or apex navigation files are replaced. The standalone
Next server rewrites `/v1/conversation/*` only to its configured exact internal
API origin. Cross-host AC session/login routing is an outstanding deployment
integration requirement; the local browser proof uses one origin. The local
static preview is not a deployable public service.

## Authenticated API

All private routes resolve the existing AC cookie, current session and active
membership. IDs belong to the current person and server-selected tenant. Client
tenant/person selectors and query parameters are rejected. Private responses use
`Cache-Control: private, no-store`; ordinary IDOR reads return 404 and revoked
permission returns 403. Write routes require the approved AC Origin.

| Method and path | Behavior |
| --- | --- |
| `GET /v1/conversation/workspace` | Public connection status, sign-in destination, authenticated/intake flags |
| `GET /v1/conversation/capabilities` | Static capability contract; not provider activation |
| `GET /v1/conversation/example` | Explicitly synthetic example only |
| `GET /v1/conversation/recordings` | Up to 20 own current recordings, newest first, latest own run and `has_report` |
| `GET /v1/conversation/recordings/{id}` | Current authorized source metadata |
| `GET /v1/conversation/runs/{id}` | Current authorized run state |
| `GET /v1/conversation/runs/{id}/report` | Run state plus validated qualitative draft, or `report: null` with honest status |
| `GET /v1/conversation/recordings/{id}/transcript` | Validated transcript source hash/revision, source clock, duration and literal segments; no raw provider receipt |
| `GET /v1/conversation/recordings/{id}/measurements` | Current authorized saved C1 display, canonical C0 parent, explicit physical-channel units and decoded clock; no audio reread or inference |
| `GET /v1/conversation/recordings/{id}/checkpoints` | Own source-bound checkpoint metadata |
| `DELETE /v1/conversation/recordings/{id}` | Idempotent durable deletion request; blocks further use and erases private descendants through worker |
| `POST /v1/conversation/intake/quote` | Configured private composition: checks explicit allowance/storage capacity and returns exact local-processing quote |
| `POST /v1/conversation/quotes/{id}/approve` | Accepts that quote fingerprint/privacy revision; no implicit provider permission |
| `PUT /v1/conversation/recordings/{id}/source` | Accepted quote required via `X-Analysis-Quote`; exact length/hash, bounded original octet stream |
| `GET /v1/conversation/recordings/{id}/source` | Authorized private playback, one HTTP byte range, no path or external bearer URL |
| `POST /v1/conversation/runs` | Reserves allowance/budget and enqueues exact supported recipe through existing PostgreSQL jobs/outbox |
| `POST /v1/conversation/recordings/{id}/analysis/quote` | Approved composition only: issues an exact source-bound C2/C4/C5 quote with explicit limits; does not approve or execute it |
| `POST /v1/conversation/recordings/{id}/analysis` | Records exact owner consent and reserves/enqueues the selected approved stage |
| `GET /v1/conversation/recordings/{id}/analysis` | Current owned persisted stage state; no execution from reads |

Registration, quote creation, run creation, deletion and admin saves take
`Idempotency-Key`. The current intake recipe produces C0/C1 local measurements.
`completed` with `report: null` must not be presented as a generated sales report.
Transcript absence before report availability is normal; clients poll status first.
The new analysis routes use the separate hash-pinned release approval described in
`docs/evidence/SALES_XRAY_HOSTED_AUTHORITY.md`. They do not accept learner-selected
providers, models, profiles or credential references. Automatic progression is
explicitly false until a durable processing-plan controller is connected.

## Admin controls and local proof import

`GET/POST /v1/admin/conversation/providers` require the exact admin surface,
verified `admin@authorityclosers.com`, active owner/admin membership and current
`admin_surface` permission. Saves append immutable configuration revisions, require
`expected_revision`, and return 409 on stale state. Learners cannot configure
providers. Inputs contain external `ref:` references, not credential values.
The response explicitly declares zero paid allowance and
`execution_activated: false`. Dormant adapters do not become implemented by saving
a configuration. Current provider/task readiness is exposed in the catalog.

`POST /v1/admin/conversation/runs/{id}/draft` exists **only** when local/test
composition explicitly supplies private import storage. Hosted composition rejects
that activation. It links an already-produced draft to an owned, completed local
run with a verified C1 source manifest and retained original bytes. It rehashes
native transcript bytes, validates source-clock spans and literal quotes, binds the
frozen Dipak profile and stores the draft/normalized transcript immutably.

The approval, generation and source-review hashes in `PrivateProofReference` are
**opaque operator-supplied external references**. This path does not retrieve or
authenticate those receipts and does not attest provider execution, external
consent or human review. Only its native transcription hash is verified against
the supplied raw bytes. It must never substitute for canonical broker receipts or
activate hosted inference. Every imported report remains an AI draft with Dipak
review pending, and numerical scoring remains withheld (95 actual / 100 declared).

## Migration and release allowlist

Migration `20260913_0030_sales_xray` extends current AC metadata with source,
permission, quote, checkpoint, run, ledger and admin/report tables. It preserves
pre-existing tenants and immutable history; report erasure nulls private payload,
transcript and receipt contents while retaining audit hashes. No operational
direct-SQL recovery or production bootstrap is part of this change.

New paths: `apps/sales-xray-web/`, new learner/admin `app/sales-xray/` routes,
`packages/typescript/sales-xray-client/`, Python `conversation_intelligence/`,
the four `http/conversation*.py` modules, local-only `development/sales_xray_app.py`,
migration 0030, `native/audioatlas/`, `infra/conversation-worker/`, scoped tests
and Sales Xray contract/evidence/implementation documents.

Shared edits: model registration in `db/models.py`, optional HTTP composition in
`http/app.py`, exact request limits, related composition tests, pnpm workspace/lock
and generated-output ignores. No existing LMS navigation, release manifests,
identity implementation, apex routing, secrets or production DB data are changed.

The internal durable C2-C6 worker, source-owned hosted API composition and
single-consent processing plan now have separate implementation evidence. The
`/recordings/{id}/plan/quote` POST, `/plan` acceptance POST and `/plan` progress GET
are the Call Studio workflow; learners do not select internal checkpoints or
providers. Migration0032 and the plan/retention scheduler contracts are documented
in `docs/evidence/SALES_XRAY_PROCESSING_PLAN.md`.
Dedicated confined Linux worker composition, approved actual
storage/allowance/provider configuration, regular scheduler invocation, current
KVM4 capacity, complete hosted browser acceptance, canary and rollback remain
required before claiming the product is live. First acceptance uses the existing
learner[-staging] `/sales-xray` path and its AC authentication continuity.
