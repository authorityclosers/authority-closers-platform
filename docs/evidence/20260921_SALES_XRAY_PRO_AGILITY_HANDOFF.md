# Sales Xray Pro agility handoff

Date: 2026-09-21  
Reviewed release: `d9de421627b89cb133344cc9a96633813f171005`  
Decision lane: ChatGPT Pro, Authority Closers Chrome profile  
Decision: **GO for behavior-preserving policy extraction and local verification; HOLD production, live limit increases, and a new report contract.**

The Pro review confirms that the problem is a distributed contract, not one number. Product choices, implementation capacity ceilings, and schema contracts currently share constants. Moving those constants into database rows without separating their roles would make accepted plans change meaning or fail validation.

## What is still embedded

- Guest allowance (`ALLOWANCE_SECONDS=3600`) is both a product entitlement and an accounting safety boundary.
- The 32 MiB upload limit is repeated in the browser, source/intake contracts, storage and provider transport.
- The 3,600-second native duration is coupled to decoded samples, feature-row count, scratch space, memory and deadlines.
- C5 repair is coupled to `C5_AUTO_REPAIR_ATTEMPTS`, `C5RepairIntent.attempt`, recursion prevention and cumulative cost calculation.
- Completion allocation still calls a code-owned `stage_completion_limit()`; freezing the approved maximum alone does not freeze the allocation algorithm.
- Report prompt/token envelopes, evidence quote size, provider-extras bytes/depth, fixed dimensions/sections, and report cardinality are split between `reports.py`, `report_overview.py`, Gemini adapters and the checked-in profile.
- Outbox lease, retry count, jitter and delay are recovery policy with hard release ceilings, not arbitrary admin sliders.
- Browser policy values are validation ceilings, not just display fallbacks; changing the server alone leaves older clients incompatible.

## Target design

Add one append-only `AnalysisPolicy` composition and one append-only `ReportProfileRegistry`, with a shared immutable envelope:

`tenant_id`, logical ID, revision, schema version, parent revision, canonical content hash, canonicalizer version, created-at/by, reason, approval reference, payload, and a compare-and-swap activation event.

The analysis payload should reference intake/entitlement, provider activation, analysis settings, stage/chunk/completion budgets, generation profile, report profile, recovery contract, pricing/FX snapshot, budget policy and qualified runtime profile. The report payload should contain stable field/section IDs, labels, definitions, applicability, ordering/cardinality, evidence requirements, missingness semantics, renderer/export versions, and migration references. It must remain declarative: no executable code, SQL, network URLs or arbitrary expressions.

The effective execution value is resolved as:

`product policy ∩ owner entitlement ∩ approved route ∩ qualified runtime capacity ∩ authorized budget`.

Plans freeze the resolved values, profile/pricing/runtime references and hashes. Later activation affects new plans only. Rollback appends an activation event; it does not mutate existing jobs or reports.

## What can move to data and what cannot

Move guest/account entitlements, product byte/duration limits within a qualified profile, repair policy, route allocations, prompt/profile revisions, report field mappings, pricing snapshots, and bounded retry policies into audited revisions.

Keep native/process isolation, parser/evidence byte-depth caps, source/evidence binding, consent/provenance/retention, idempotency, provider/model approval, budget/authority checks, and release compatibility as reviewed safety ceilings. Admin may select approved values but cannot widen those ceilings without a new release/approval bundle.

Generate Python/TypeScript schemas, enums, stable error codes and structural ceilings from one contract source. Fetch effective upload limits, formats, retention, allowance, profile revision and presentation metadata through the existing entry/upload-policy/session surfaces. If policy is unavailable, show checking/unavailable; do not invent an entitlement.

## Required proof before activation

1. Seed revision 1 from current behavior and prove byte-for-byte request/report compatibility.
2. Add a shadow resolver and compare every consumer before changing dispatch.
3. Prove accepted plans ignore later policy/profile activation, while revoked/expired authority still holds before dispatch.
4. Prove tenant isolation, activation CAS, distinct policy/binary rollback, provider drift rejection, optional report field addition/removal/reordering, and cumulative finite repair cost.
5. Prove C5 repair reuses valid C2/C4 without a new upload or duplicate provider calls.
6. Prove limit−1/limit/limit+1, UTF-8, oversized segment, progress beyond the first page, varied ASGI chunk partitioning, duplicate delivery and crash recovery.

The Pro review found no evidence that one current constant is the confirmed cause of the earlier generic upload failures. The 17.6 MB fixture was below the nominal 32 MiB limit; the actual status, byte count, selector and durable boundary were not captured. Upload/native deadline interaction and per-event chunk rejection remain inspection targets. This agility work is therefore separate from, and cannot be used to claim closure of, the real staging upload-to-report acceptance gate.
