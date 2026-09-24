# Report quality and cost benchmark readiness

Audit base: v0.2 candidate `eb4d6ac48173d82efa9ca24ec15696a686465027`, built from source baseline `c8f16cb2330008ada6374663d0a7d2442aec6532`; deployed runtime baseline `270a4b57e39646ba6b5e171614bc9ef114091d09` (`270a4b57`). This is a source review plus a focused offline contract-test run. No provider calls, database writes, budget changes, SSH operations, or live report inspection were performed.

## What the candidate changes

The current release default remains English `coaching-v3`: `analysis_settings.py:31-62` defaults to v3/English, and `processing_plan.py:91` keeps new plans on v3. The v0.2 candidate adds explicit, frozen `coaching-v4` with report language and qualitative-pack hash binding. `reports.py:1863-1943` builds the v4 prompt, checks the exact pack hash, and rejects language/hash options on old prompt revisions. The three supported modes are `en`, `hi-Deva+en`, and `mr-Deva+en`.

The source-bound pack (`profiles/sales_xray_qualitative_20260922.json:4-171`, SHA-256 `e5f831477b715833d7163dfb49370751a348fb2498565d95ff83ea57838ee4ca`) declares single-call scope and `numeric_evaluation: false`. Its ten rules cover evidence versus interpretation, preservation of exact quoted evidence and contradictions, role/sequence, objection interpretation, useful discovery, unsupported commercial claims, modality limits, specific coaching, and no unsupported longitudinal claims. The cited Brain 2.0, Brain 2.1, and Context/Role sections are recorded in the pack and tied to captured source hashes in `docs/plans/sales-xray-v02/source-intake.json`.

That establishes a traceable candidate instruction set, not complete adoption of every Dipak requirement. The intake manifest identifies 12 source entries, but the pack binds three, and the manifest explicitly records that the knowledge dump was not reviewed line by line (`source-intake.json:215-217`). The detailed report and report-structure sources also request scorecard/closer-level sections; the current pack does not approve numeric evaluation. Do not use scorecard coverage as an acceptance claim before the AC-SVAL gate. The requested Devanagari/code-switched language instructions are present, but no native-speaker quality result is recorded. Prompt construction and preserved source quotations do not prove that generated Hindi or Marathi prose is fluent, accurate, or useful.

## Evidence that exists—and what it proves

The old `270a` acceptance record documents successful operational runs: two short fictional production calls completed C2/C4/C5, and a separate approximately 60-minute staging fixture exercised the then-current English coaching path. This is successful workflow/provider evidence, not a paired v3/v4 report-quality benchmark. The record has no blinded reviewer comparison or v4 generated report, and the long-call report is not evidence of v4 quality.

The existing executable offline benchmark (`benchmark.py`, `benchmark_cli.py`, `docs/contracts/SALES_XRAY_OFFLINE_BENCHMARK_V1.md`) compares synthetic C4 context/profile behavior. Its eight fixture cases and two candidates cover context and admission expectations; they do not generate or grade C5 reports. The 2026-09-14 evidence records 16 declared fixture comparisons passing, zero provider/ASR calls, and ₹0 provider cost. It explicitly disclaims model-quality evidence (`docs/evidence/20260914_OFFLINE_BENCHMARK.md:60-89`).

For this audit, the existing qualitative-pack, prompt, and report-language contract tests passed: **25 passed**. They verify pack identity/source references, v1-v3 prompt byte compatibility, v4 hash/language requirements, distinct prompt identities per language, and unchanged source evidence. They do not call a model or evaluate generated text. A separate retained `v4-hour-context-proof.json` reports offline context/capacity success, five fact chunks, all three language configurations, zero provider calls, and zero database writes; it is not provider acceptance, quality evidence, or cost evidence.

Admin reflects the same boundary: the Benchmark Center says test-run controls and benchmark/probe endpoints are unavailable (`apps/admin-web/app/sales-xray/benchmark-center.tsx:111-207`). Provider settings and reviewer assignment are not executed benchmark evidence.

## What can be compared without paid calls

The reproducible offline comparison available now is a contract and input-construction comparison using identical synthetic transcript/fact packets:

1. Verify v3 prompt hashes remain unchanged and v3 rejects non-English options.
2. Build v4 prompt inputs for English, Hindi-English, and Marathi-English against the same source-bound packet and exact pack hash.
3. Compare prompt/input hashes, UTF-8 prompt size, source preservation, and output-schema constraints. Keep language variants separate because each has a distinct input hash. Only report token counts if the exact tokenizer for the pinned model is available, and label them as local estimates rather than provider usage.
4. Record the output only as prompt-construction, size, or contract evidence. No report-quality winner, fluency result, latency claim, or hosted cost follows from it.

This was exercised by the 25 passing tests above. The existing synthetic context benchmark can also be rerun, but it cannot answer whether v4 reports are better. Without generated v4 output, a source-paired, blinded human review of v3 versus v4 is not available offline. A defensible quality comparison needs the same frozen source, transcript, C4 facts, model/configuration and English output mode, differing only in coaching revision; v4 language quality additionally needs qualified reviewers for each requested language. Use permitted synthetic or consented, retention-cleared material, a source-based rubric, blinded order, and adjudication. Do not convert those human labels into official autonomous scores.

## Usage and cost measurement boundary

Current source already provides useful attribution:

- Audio usage is recorded as admitted `reserved_seconds` and a separate `charged_seconds` settlement, associated with person or visitor and submission (`acquisition_models.py:66-120`). This measures source-audio entitlement, not a currency charge.
- Analysis runs/tasks retain person, recording, stage, job, and run identifiers (`models.py:100-123, 380-416`). A provider receipt can retain provider/model, provider request ID, idempotency key, stage/run lineage, and bounded usage counters such as input/output tokens (`inference_worker.py:88-176, 650-675`). Person grouping is derivable for recorded tasks, but the reviewed Admin surface has no dedicated per-user cost ledger or aggregate.
- Admin computes per-provider-stage usage estimates: C2 from native audio duration where available; token-priced C4/C5 from provider token counters and an approved planning-rate snapshot (`admin_pricing.py:133-220`). The snapshots mark `is_billing_rate: false`; estimates can be unavailable when usage or a rate is missing.
- The recording inventory separates reservation ceiling, estimate, usage estimate, and settled actual. It only reports `actual_paise` when all relevant reservations have typed settlement receipts (`admin_recordings.py:440-555`; `recordings-api.ts:175-214`). A `SettlementReceipt` has provider, attempt, actual seconds/paise, and receipt reference (`entitlements.py:228-242`).

These fields support per-call and per-stage observed usage plus planning estimates, and actual cost only after receipt-based settlement. They do **not** establish billed cost for every provider return: worker receipts set `actual_cost_paise: null` and `cost_state: reconciliation_required` (`inference_worker.py:150-176, 658-675`). The usage estimator prices prompt/input tokens at the ordinary input rate and does not apply the separately retained cached-token counter (`admin_pricing.py:198-220`); that estimate must not be read as billing. A single retained job receipt is not a normalized ledger of every wire attempt/retry; ambiguous or failed dispatches can lack usage and must remain uncertain rather than be counted as free. The reviewed Admin surface displays per-recording summaries, not a company-wide settled-cost rollup or a per-user cost ledger.

The next internal ledger can safely aggregate from immutable source events, without changing customer credits or pricing: owner/person or visitor, submission/recording, run/analysis, stage, exact job/idempotency key, each provider attempt/request ID, provider/model/revision, native audio milliseconds, input/output/thought/cache token counters, reservation ceiling, rate/FX evidence snapshot, estimate state, settlement receipt reference, actual amount, and uncertainty/reconciliation state. Keep audio seconds separate from provider spend. Derive per-call/provider cost and company totals only by summing appropriately scoped event/settlement rows; preserve `unknown`, `partial`, and `unsettled` states.

One C5 provider request produces the whole report. Its receipt can support a C5 request-level usage/cost estimate, but cannot measure exact spend for an individual report section. Section-level figures would be an allocation policy, not observed provider cost; label any such allocation explicitly and do not present it as measured.

For an honest average cost per original audio minute, calculate `sum of reconciled C2 + C4 + C5 (+ separately recorded retries)` divided by the same call's native audio minutes. Call this an observed average per source-audio minute, not the provider's minute tariff: C4/C5 are token-priced and retries can incur separate charges. Report estimates separately from actuals, and pair runs under the same pricing/FX snapshot or normalize against a declared common snapshot. A company total is meaningful only for a defined period/scope with complete settled rows and explicit treatment of unresolved attempts.

The testing figures are ceilings/holds, not costs: tracked request ceilings are ₹639 of the ₹1,000 task ceiling; the separate staging ledger shows ₹1,085 in unresolved dispatched holds. These scopes are not a reconciled bill, cannot be treated as additive or subtracted to infer remaining spend, and have no safe free release established. No per-minute price can be calculated from them.

## Conclusion

Current evidence supports: v4 pack/prompt contracts pass offline; v4 can be compared structurally with v3 without provider spend; existing Admin can show request/stage usage estimates and settled per-call actuals when receipts exist. It does not support a report-quality superiority claim, a live v4 quality result, a complete per-attempt ledger, a company-wide actual-cost total, or per-minute actual cost. Those require paired report outputs and human review for quality, plus immutable attempt-level usage and provider settlement/invoice reconciliation for cost.
