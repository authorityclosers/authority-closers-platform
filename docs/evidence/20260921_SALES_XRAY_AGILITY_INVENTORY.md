# Sales Xray agility inventory

Date: 2026-09-21  
Source revision: `d9de421627b89cb133344cc9a96633813f171005`  
Scope: upload admission → C2 transcription → C4 facts → C5 coaching report → C6 presentation/recovery.

This is an implementation inventory, not permission to edit production state. Values below are classified so a future Admin/CLI surface can expose product decisions without weakening consent, provenance, evidence, billing, or release identity.

## Already revisioned and usable

| Area | Current source | Current behavior |
| --- | --- | --- |
| Provider configuration and activation | `packages/python/ac_platform/conversation_intelligence/provider_registry.py`, `provider_admin.py` | Append-only configuration and activation revisions; accepted plans retain the selected route. |
| Analysis limits | `analysis_settings.py`, `analysis_settings_admin.py`, `analysis_settings_cli.py` | Tenant-scoped revisions for C4 request/token limits, C5 completion limit, and output profile. New plans read the latest revision; accepted plans remain frozen. |
| Shared budget | `budget_admin.py`, `budget_cap_cli.py`, activation bundle | Revisioned and approval-bound; a persisted cap cannot silently exceed the release approval. |
| Acquisition policy | `activation_contract.py` | Source size, storage, stage routes, expiry, and processing principal are bound to a signed approval bundle. |
| Provider response compatibility | `reports.py` | Recognized flattened/nested provider shapes are normalized; bounded provider-only sections are retained in `provider_extras`. |

## Product decisions still embedded in code or checked-in profile data

These should become fields in a versioned, audited policy/profile registry. They must be resolved once when a plan is quoted and copied into the immutable plan manifest.

| Decision | Current location | Why it is a product knob | Safe target |
| --- | --- | --- | --- |
| C5 automatic repair count | `processing_plan.py:79` (`C5_AUTO_REPAIR_ATTEMPTS = 1`) | Determines whether a valid provider response gets one bounded repair attempt. | `c5_auto_repair_attempts`, bounded by a release maximum and each stage's approved request count. |
| Report input character budget | `processing_plan.py:159` (`Literal[16000]`) and `reports.py:38` | Controls how much transcript/fact context reaches a report request. | Integer policy field with provider/profile envelope validation; remove the business-policy `Literal` while retaining a release hard cap. |
| Route completion ceilings and paid threshold | `completion_limits.py:4-15` | Maps provider/model/stage to output capacity and a cost approval threshold. | Versioned per-route limits and cost rule, intersected with release safety maxima and the approved budget. |
| Provider model/task allowlist | `gemini_tasks.py:17`, `provider_registry.py` catalog | Determines which provider/model can run facts or coaching. | Approved catalog/profile revision; Admin can select only catalog entries with an implemented adapter and current approval. |
| Gemini generation envelope | `gemini_tasks.py:19-21, 31-65` | Thinking level, response bytes, and total prompt/output budgets affect quality and spend. | Versioned adapter profile with allowlisted enum values and bounded byte/token caps. |
| Retry/backoff policy | `providers/service.py:156-157, 332-351`, `outbox/repository.py:165-187, 674-698` | Controls recovery latency and attempt count. | Keep transport safety bounds release-bound; expose only bounded route/job policy fields with idempotency and spend fencing. |
| Report overview version/template | `report_overview.py:16-18, 133-146` | Controls the presentation contract and its fixed field/cardinality limits. | `ReportProfileRegistry` revision with a source digest and allowlisted schema/mapping. Existing plans retain their profile revision. |
| Dipak dimensions and sections | `profiles/dipak_report_v1.json`, `reports.py:299-323, 1037-1162` | Defines the sales-specific dimensions, sections, citations, and wording. | Versioned profile revisions; new fields/mappings are additive or explicitly superseding, never a silent rewrite of old reports. |
| Provider pricing and FX | `admin_pricing.py:21, 74-110` | Changes usage estimates when provider prices or INR/USD assumptions change. | Append-only pricing snapshot with source URL/ref, effective date, approval, and FX revision. Historical receipts keep the old snapshot. |
| Client policy fallbacks | `apps/sales-xray-web/app/acquisition-client.ts:31, 215, 233, 238, 274-279` | The browser has defensive fallback values (32 MiB, 3,600 seconds, 6,000 allowance seconds) and duplicates the server upper bound. These are not authority, but they can make a changed policy look stale or hide a malformed policy response. | Treat the server policy as required for display and admission; retain only a clearly named release safety ceiling in the client, or generate the typed contract from the server schema. Add a test that missing policy values fail closed with an actionable error rather than silently substituting product values. |

## Safety invariants that must stay release-bound

These are not arbitrary Admin knobs: native process isolation and resource ceilings (`native_runtime.py`), parser/response byte and depth limits (`gemini_tasks.py`, `reports.py`), source/evidence binding, consent/provenance/retention, idempotency, budget approval, allowed provider protocols, and rollback/release identity. An Admin UI may select among approved values but cannot widen these limits without a new reviewed release/approval bundle.

## Target configuration contract

Create one append-only `AnalysisPolicy` aggregate and one append-only `ReportProfileRegistry`:

```json
{
  "policy_revision": 1,
  "status": "approved",
  "supersedes_id": null,
  "effective_at": "2026-09-21T00:00:00Z",
  "analysis": {
    "c4_max_requests": 64,
    "c4_max_completion_tokens": 1400,
    "c5_max_completion_tokens": 3200,
    "c5_auto_repair_attempts": 1,
    "max_input_chars": 16000,
    "output_profile": "detailed",
    "route_profile_revision": "provider-catalog-20260914-v1"
  },
  "report_profile_revision": "dipak-14-point-v1",
  "pricing_snapshot_revision": "pricing-20260914-v1",
  "approval_ref": "ref:analysis-policy-..."
}
```

The aggregate must validate bounds and unknown keys, record actor/reason/idempotency, and expose a read-only effective-policy view. Draft → approved is an explicit operation. A plan stores the resolved values and profile/pricing digests; retries and replays use that frozen snapshot. Retiring a revision affects only new plans. If the registry is missing or invalid, use the last approved revision; if none exists, hold before provider spend while preserving the recording, transcript, and raw receipt.

## Report field/mapping registry

The registry should describe each canonical field with:

- canonical path and display label;
- provider source paths (flattened and nested aliases);
- type, length, cardinality, and ordering rules;
- whether evidence is required and how transcript spans are bound;
- missingness policy (`unknown`, `insufficient_evidence`, `not_applicable`, `conflicted`);
- presentation section and versioned copy key;
- a bounded `extras` namespace for provider additions.

Unknown provider fields can be retained for review, but they cannot become canonical findings until a reviewed mapping revision exists. Unbound or ambiguous evidence remains a recoverable report-draft/repair state; it must never become fabricated evidence or force a re-upload.

## Migration and acceptance sequence

1. Backfill current constants/profile/pricing into revision 1 with byte-for-byte behavior.
2. Add a shadow comparison that rejects drift between the old constants and revision-1 values before activation.
3. Deploy read/freeze support, then the Admin/CLI writer and approval UI, then worker consumption behind a feature flag.
4. Add property and integration tests for bounds, tenant isolation, approval history, plan freeze, retry/replay, rollback, missing registry fallback, provider-shape normalization, evidence failures, and pricing snapshots.
5. Prove a synthetic guest and authenticated upload through report-ready C6 with zero duplicate provider effects before promoting the feature.

The key design rule is: **make product decisions data-driven, but make safety and evidence rules release-bound.** That gives us fast Admin/CLI changes without repeating the release mismatch and without making a bad report look successful.

## Additional fixed contracts found in the report and recovery layers

These are easy to miss because they are schema or adapter constants rather than Admin settings. They still need an explicit classification in the future policy registry.

| Decision | Current location | Classification and migration rule |
| --- | --- | --- |
| Report request token/prompt envelopes | `reports.py:36-46,203,592-727`, `gemini_tasks.py:19-21,31-65` | Product quality/cost knobs intersected with provider and release ceilings. Version the envelope per route; freeze its digest in the plan. |
| Evidence quote length, provider extras bytes/depth | `reports.py:40,45-46,132,800-814` | Safety/parser bounds. Keep release-bound; allow profile copy/mapping changes without changing evidence admission. |
| Exact dimensions/sections and finding cardinality | `reports.py:252,307-323`, `report_overview.py:59,73,87,133`, `profiles/dipak_report_v1.json` | Current report schema/profile, not a generic limit. Move to an append-only profile registry with schema version, required fields, aliases, ordering, cardinality and migration renderer. |
| Outbox lease, retry attempts, jitter and delay | `outbox/repository.py:46-47,165-212,674-698` | Recovery policy with release hard ceilings. Expose route-specific values only through approved policy revisions; never let Admin create unbounded retries or retry an uncertain provider effect. |
| Acquisition/session and native deadlines | `acquisition_sessions.py:70`, `acquisition_usage.py:23`, `conversation_submissions.py:76`, `signals.py:33`, `limits.py:3` | Product capacity values are duplicated across admission, native measurement and browser contracts. Make one effective server policy; retain separate release safety maxima and prove all callers consume the same resolved snapshot. |
| Library/progress page sizes and task cardinality | `acquisition_library.py:24`, progress/report contracts and client parsers | UX/pagination knobs can be revisioned independently. They must not be confused with completeness limits; a page boundary must never drop a task or report section. |
| Provider model/task allowlists and thinking mode | `gemini_tasks.py:17-21` and provider catalog | Approved capability catalog. Admin may select only a catalog entry with an adapter, pricing, budget and active approval; arbitrary model strings remain invalid. |

The practical failure pattern is therefore a **distributed contract**, not one bad magic number: changing a value in one layer can still leave a browser parser, Pydantic bound, native decoder, report schema, outbox policy or release approval rejecting the same work. The migration must start by emitting an effective-policy manifest and comparing every consumer against it before any value is changed.

## Runtime proof discovered after the inventory

The staging worker was restarting before it could open its database or dispatch a provider. Its bind-mounted service manifest was `root:root` mode `0440`, while the dedicated container runs as UID/GID `10001:10001`; the worker therefore failed its private-file read with `worker_file_unavailable` and emitted only the old generic `worker_service_failed` marker. The canonical release controller now repairs only this metadata (root owner, group `10001`, mode `0440`) without changing manifest bytes or its digest, and the worker retains a stable sanitized failure code in logs. This is a release/install contract and belongs in deployment verification, not in an Admin setting.

## Contract-drift proof from the live Admin surface

The staging Admin recordings endpoint emits two additive diagnostic fields that
older Admin builds did not model: `submission_id` (the acquisition join key)
and `runtime_trace` (read-only plan/task/publication joins). A strict client
parser rejected these fields before an operator could inspect the held
recording. The Admin client now accepts the optional acquisition join and a
bounded, forward-compatible diagnostic object while keeping canonical identity,
ownership, status, cost, report eligibility and provider receipts strict. The
regression test also proves that a future diagnostic key survives parsing.

This is the migration rule for future fields: classify each field as either a
canonical decision/evidence contract (version and validate it strictly) or an
additive diagnostic/provider extension (bound its size and preserve unknown
keys). Never make a new optional diagnostic field capable of invalidating the
entire review page.

## C5 provider-shape proof from a real staging response

The retained staging C5 response for run `dfec5a4a-5a7a-437e-96df-a27a206ddaad`
was valid Gemini JSON and contained source-bound overview spans, but its
`strengths`, `missed_opportunities`, and `improvements` arrays used prose
strings instead of the canonical `{title, explanation, evidence[]}` shape.
The old parser rejected the complete report with
`conversation_report_findings_invalid`, leaving the provider receipt in
`reconciliation_required` and the plan held. The parser now applies a bounded
compatibility adapter: overview evidence can derive the canonical improvement
and missed-opportunity finding; a prose-only claim is retained under bounded
`provider_extras.compatibility.unbound_findings` and omitted from canonical
evidence. No evidence is invented and no recording re-upload is required.

Local reproduction against the saved provider bytes and the native transcript
produced a normalized draft with one evidence-bound improvement, one
evidence-bound missed opportunity, zero fabricated strengths, and the original
unbound strength preserved as provider extras. Focused report/overview/inference
tests pass (`92` tests), Ruff and mypy pass for the changed module. This is a
code candidate only; staging and production still require the approved
release/install path and a fresh durable-report proof.
