# Sales Xray agility inventory

Date: 2026-09-21  
Source revision: `2a0c64aa53d2dd5aae6dff1bbc9c386da15cef3a`  
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
