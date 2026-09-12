# Sales Xray benchmark plan

This plan defines a reproducible, provider-swappable benchmark for the Conversation
Intelligence path. It keeps the cheap, source-bound stages reusable while comparing
ASR, fact extraction, retrieval, reranking, coaching, and presentation adapters under
the same input, permissions, profiles, and review rules.

The benchmark is an internal decision aid. It does not create an official score,
training label, sales claim, or provider endorsement. All numerical quality values
proposed below are pilot defaults pending explicit owner approval; they are not source
document thresholds.

## Source basis and authority

The controlled ZIP is the authority for the constraints below. Section names are
quoted so a future revision can be reconciled rather than silently blended with this
plan.

| Source | Exact section | Constraint used here |
| --- | --- | --- |
| `docs/CALIBRATION.md` | `Dataset and permission contract` | Every case has checksum, owner, purpose, allowed providers, language/script, call type, channels, duration, condition, split, and permission metadata. Operational permission and training permission remain separate. |
| `docs/CALIBRATION.md` | `Offline stage: spend ₹0 on inference` | Use deterministic audio fixtures, malformed responses, forged references, and fixture observations before any inference spend. Synthetic success is not a language-accuracy claim. |
| `docs/CALIBRATION.md` | `Paid stage plan (usage estimates, no purchase made)` | The ₹90/USD estimates and ₹1,500 normal/₹2,000 absolute owner ceilings are planning figures only. No purchase is authorized by this plan. |
| `docs/CALIBRATION.md` | `Avoid the Cartesian-product bill` | The 432 design combinations are a planning enumeration, not 432 executable candidates. Gate capabilities and reuse checkpoints before screening. |
| `docs/CALIBRATION.md` | `Required metrics` | Measure speech, signals, context, coaching, and engineering outcomes, including cost, retries, latency, deletion, and authorization failures. |
| `docs/CALIBRATION.md` | `Dipak and Suyash review lanes` | Dipak reviews contextual usefulness and sales claims; Suyash reviews measurement, attribution, and source integrity. |
| `docs/CALIBRATION.md` | `Release evidence and stopping rules` | Freeze gates before holdout inspection, report call-level uncertainty and slice failures, withhold public numerical scores until the 95/100 mismatch and coverage policy is approved, and never use automatic training. |
| `docs/PROVIDERS_AND_KEYS.md` | `First accounts`, `Optional challengers` | Start with a small capability-qualified set. Optional providers are not enabled merely because they exist. |
| `docs/PROVIDERS_AND_KEYS.md` | `Enter keys without copying them into a prompt` | Provider secrets stay in approved external secret handling and never enter Git, receipts, prompts, or logs. |
| `docs/PROVIDERS_AND_KEYS.md` | `Reference transport gate` | Paid execution is opt-in, bounded by exact input/payload checksums and integer-paise budget admission, and unknown/timeout attempts are not automatically retried. |
| `docs/IMPLEMENTATION_PLAN.md` | `Slice 1 — local deterministic evidence path` through `Slice 6 — staging, canary and production` | Follow the offline, authenticated local, restricted staging, and later canary progression; preserve native measurements, manifests, cleanup, deletion, and rollback evidence. |
| `docs/IMPLEMENTATION_PLAN.md` | `Verification ladder` | Advance from offline unit/property checks to local ASGI, browser/network development checks, authorized provider smoke, restricted staging, small real data, and only then production. |
| `agent_briefs/provider_eval.md` | `provider_eval` | Adapters own capability gates and usage receipts; execution is staged, transactional, and fail-closed around privacy, tariff, budget, and duplicate-spend risks. |

The checked-in implementation supplies additional binding contracts. Checkpoint
lineage is `C0` source/permission, `C1` measurement, `C2` transcript/speech, `C3`
alignment/attribution, `C4` context/offer, `C5` profile/judge, and `C6`
publication. `SourceBinding`, immutable checkpoints, exact parents, canonical
configuration, and `manifest_sha256` are the identity used by benchmark receipts.
The report parser remains qualitative: numeric fields are rejected and every finding
must cite an exact transcript span.

## Benchmark question

For one authorized source and one frozen task specification, which eligible adapter
recipe produces the most useful, source-grounded result at acceptable reliability,
latency, and cost, while preserving tenant, source-version, deletion, and review
boundaries?

The unit of comparison is a **recipe**, not a raw model. A recipe names the adapter
for each task, the exact model and endpoint, prompt/profile revision, native extractor
revision, retrieval index revision, reranker revision, and presentation schema. A
recipe cannot compare a provider on a different transcript or a different permission
scope.

## Dataset and split protocol

The source diagnostic set is 30 short calls or excerpts totaling 240 minutes: 20
development/calibration cases and 10 sealed holdout cases, with speaker/customer
disjointness. This is the source-defined diagnostic shape from `Dataset and
permission contract`. Long calls, Marathi or code switching, telephone compression,
and overlap are expansion slices; the initial set must not imply coverage of them.

Before execution, the owner-approved manifest must make development and calibration
distinct rows. **Proposed pilot allocation:** 12 development cases and 8 calibration
cases inside the source-defined 20, plus the source-defined 10 holdout cases. This
12/8 split is proposed, not an official ZIP threshold. If the manifest cannot support
it without partition leakage, stop and record the blocked split instead of borrowing
holdout data.

Each manifest row is metadata-only in Git and includes:

- `case_id`, `source_sha256`, `participant_partition_sha256`, `split`,
  `permission_ref`, and `manifest_revision`;
- owner, purpose, allowed providers, language/script, call type, channel count,
  duration, condition, and source revision;
- tenant and source-version binding, retention/deletion state, and permitted output
  kinds;
- fixture class or slice tags such as silence, clipping, noise, overlap, amounts,
  dates, negation, objection, code switching, or telephone compression.

Raw recordings, real names, provider keys, holdout transcripts, human labels, and
pre-generated holdout outputs stay outside Git and outside development prompts. A
case may be used operationally without acquiring permission to train on it. Holdout
bytes and labels are never passed to correction-fixture generation, calibration, or
model prompts.

The current real-call status is context, not benchmark evidence: one call has 144
segments; both Groq coaching drafts failed; a source-corrected private-AI draft was
delivered; and five private reproduction proposals exist. Those outputs and any
associated keys remain unread and are not imported into this benchmark or used to
claim accuracy.

## Execution stages and gates

| Stage | Inputs and work | Required result before advancing |
| --- | --- | --- |
| Offline, ₹0 | Deterministic WAV/PCM fixtures, known gaps, silence, tones, clipping, invalid samples, stereo, tail frames, malformed provider envelopes, forged evidence references, and fixture transcripts/observations. Run the AudioAtlas local recipe and validate units, timebase, windows, float32, channel identity, and cleanup. | All contract, property, parser, lineage, deletion, and failure tests pass. No network or provider call is permitted. |
| Authenticated local, ₹0 | Run through local authenticated tenant/session APIs with synthetic fixtures only. Exercise quote/approval, source revision, C0/C1/C2/C3/C4/C5/C6 lineage, cache reuse, revocation, expiry, deletion, and crash/recovery paths. | Server-authorized run IDs, immutable receipts, no cross-tenant/source-version reads, no residual scratch, and truthful failed/unknown states. |
| Restricted staging, future and owner-approved | Use only an approved provider, approved authorized cases, a bounded recipe set, explicit quote/consent, integer-paise reservation, and isolated staging keys/storage/quotas. | Every call has a complete usage receipt, no duplicate spend, budget settlement, redacted evidence, review binding, rollback pointer, and owner approval for the next gate. |
| Small real, future and separately authorized | Evaluate only after restricted-staging gates, with retention and deletion verified. Keep real-call results separate from synthetic and diagnostic sets. | Written approval for the scope, provider, cases, retention, and budget; a reviewed run manifest; no public accuracy claim until release evidence is complete. |

The first two stages are the only stages authorized by this plan. They must run with
provider access disabled and zero paid quota. A missing local capability is a failed
or blocked case, never a paid fallback. Unknown or timeout outcomes are receipts to
reconcile, never permission for an automatic retry.

## Task adapter contract

Every adapter implements the same logical contract, regardless of vendor. A provider
with no capability for a task is rejected before transport. OpenAI, DeepSeek, Groq,
Scribe, Gemini, Sarvam, xAI, a future private model, and a local deterministic tool
can therefore be added as adapters without changing benchmark semantics. The
capability matrix must state whether an adapter supports audio, native words,
speaker/channel timing, structured JSON, maximum input, region/retention terms, and
the task's permission class.

An adapter receipt records the task and recipe identity, provider/model/endpoint
revision, SDK and transport revision, canonical request hash, immutable input/source
hashes, timeout/deadline, budget quote and currency in paise, attempt state, response
hash or redacted response reference, output schema revision, and measured usage. It
never contains a secret, raw authorization header, or content in an exception or
`repr`. Body bytes are frozen before authorization and are not mutated after the
TOCTOU grant check. Whole-run execution has one bounded deadline and no hidden
provider retries.

Task contracts are:

| Task | Stable input | Stable output and evaluation |
| --- | --- | --- |
| `measure_audio` (C1) | Authorized source bytes, source hash/revision, format, channels, sample rate, and native recipe such as `audioatlas-48000-v1`. | Native measurements, units, window/timebase, validity masks, clipping/noise markers, extractor/version receipt, and no inferred transcript or coaching. |
| `transcribe` (C2) | Immutable source identity plus allowed language/script, channel, and timing requirements. | Native transcript, raw text, words, segments, timings, speaker/channel fields, confidence as a provider field only, and source hash/revision. Preserve overlap and uncertainty; never flatten or invent speaker attribution. |
| `extract_facts` | Complete validated C2 transcript or planned chunks; no coaching profile. | Style-independent fact packets covering every native segment exactly once, literal evidence spans, uncertainty, source hash, transcript revision, and schema revision. The checked-in `reports.py` parser is the reference contract. |
| `retrieve_evidence` | Tenant/source-version constrained fact or query representation, deletion-aware index revision, and permitted document scope. | Ranked evidence IDs, source versions, exact spans, scores as retrieval diagnostics, and freshness/deletion receipts. Retrieval can improve evidence lookup; it cannot train or alter a model. |
| `rerank_evidence` | Candidate evidence list plus frozen query/task revision. | Stable ordered candidates, tie policy, model/version, and source-bound references. No new facts or unsupported claims may be introduced. |
| `coach_or_judge` (C5) | Complete C2/C3/C4 artifacts, exact evidence, and a frozen profile/judge revision. | Qualitative findings, dimensions, uncertainty, applicability, and at most three improvements with exact citations. No numeric score, motive, identity, fixed trait, or official adjudication. Compare profiles/judges over the same C2 artifact. |
| `present_report` (C6) | Validated qualitative draft, evidence links, source/review state, and audience/readability profile. | A salesperson-readable report whose labels, evidence, uncertainty, and review status survive rendering/export. Presentation cannot change facts or hide failed/unknown states. |

The adapter boundary is also the experiment boundary. A candidate may be a local
fixture adapter, a hosted OpenAI or DeepSeek adapter, or another future task adapter,
but it must pass the same schema, permission, source-binding, deadline, receipt, and
rollback checks before it enters a comparison.

## Checkpoint reuse and recipe design

The benchmark computes C0 and C1 once per authorized source recipe, then computes C2
once per `(source, transcript adapter, model, version, input policy)` and reuses that
immutable transcript for all eligible C3 through C6 comparisons. A fresh C5 profile,
judge, retrieval index, reranker, or presentation adapter must not trigger another
ASR call. A changed source, transcript revision, native extractor, or permitted
input changes the appropriate checkpoint and invalidates descendants according to the
checkpoint lineage.

The comparison matrix is built in this order:

1. Filter providers by capability, language/timing/privacy terms, input limit,
   allowed case permission, and zero-cost stage status.
2. Freeze one recipe manifest and run C0/C1. Reject any artifact whose source or
   tenant binding differs.
3. Screen a small stratified set of C2 adapters and retain their complete receipts.
4. Reuse each retained C2 output for facts, retrieval, reranking, coaching/judge,
   and presentation comparisons. Do not form the 432-way Cartesian product.
5. Use paired cases and ablations to identify whether an improvement comes from the
   ASR, fact packet, retrieval, reranker, profile/judge, or presentation layer.

The first benchmark recipe is local-only: AudioAtlas C1, fixture/native C2
transcripts, checked-in fact/report parsers, a deterministic source-bound retrieval
fixture, and the current qualitative report profile. Hosted provider recipes are
future restricted-staging work and require a separate owner approval.

## Exact version manifest and receipts

Every run has an immutable `run_id`; every task attempt has an `attempt_id`. The
run manifest records at minimum:

```json
{
  "schema": "ac.sales-xray.benchmark-run/1",
  "run_id": "owner-approved-id",
  "stage": "offline",
  "dataset_manifest_revision": "manifest-revision",
  "case_ids": ["fixture-001"],
  "recipe_revision": "recipe-revision",
  "provider": "local",
  "model_or_tool": "audioatlas-48000-v1",
  "operation": "measure_audio",
  "prompt_revision": null,
  "profile_revision": "none",
  "retrieval_index_revision": "fixture-index-v1",
  "reranker_revision": "none",
  "code_revision": "git-commit-or-build-digest",
  "schema_revisions": ["ac.sales-xray.checkpoint/1"],
  "source_sha256": "sha256-of-authorized-fixture",
  "input_sha256": "sha256-of-canonical-input",
  "config_sha256": "sha256-of-canonical-config",
  "budget_paise": 0,
  "receipt_dir": "external-receipts/benchmarks/run-id"
}
```

The example is a shape, not an executable receipt and contains no real source hash.
The actual manifest must include exact dependency/runtime versions, native binary
digests, model/endpoint revision, prompt and profile hashes, retrieval snapshot
revision, source revision, and all parent checkpoint manifest hashes. The cache key
identifies inputs; a changed output is an immutable conflict requiring a new revision
or replicate, never an overwrite.

Receipts live outside the repository under the release-transfer receipts area, with
redaction and retention appropriate to their stage. Git stores only safe schemas,
fixture metadata, and synthetic evidence. The receipt chain must distinguish
`succeeded`, `failed`, `unknown`, `cancelled`, `revoked`, `expired`, and
`blocked_by_budget`.

## Metrics and statistical comparison

Metrics are reported by task, case, and protected slice before any aggregate. A frame
from one call is not an independent sample.

**Literal/source metrics** check exact quote equality, segment ID validity, time bounds,
source hash/revision, complete segment coverage, chunk coverage, and tenant/source
version. The publication parser must reject malformed references; a candidate cannot
average away an invalid citation.

**Semantic metrics** use a frozen rubric and blinded human review for facts, objection
links, offer/context relations, retrieval applicability, coaching usefulness, and
whether uncertainty is preserved. The evaluator records supported, unsupported,
conflicted, unknown, and insufficient-evidence outcomes separately.

**Readability metrics** test whether an ordinary salesperson can identify what
happened, which evidence supports it, what is uncertain, and the next practice action
without seeing provider/model names. Use a small, role-appropriate comprehension
exercise and record item-level answers and confusion reasons. **Proposed pilot size:**
6–8 readers and five comprehension prompts per report; this is exploratory and not a
release threshold.

**Attribution metrics** separate speaker/channel attribution, overlap preservation,
and timestamp boundary error from word error. Provider confidence is not treated as
correctness. Overlapping diarized words remain overlap; they are never silently
flattened.

**Engineering metrics** include success-inclusive cost, failed/unknown/retry spend,
queue versus compute/ASR/judge time, p50/p95 delivery, memory/disk, app latency,
deletion completion, revocation/expiry enforcement, and authorization failures.

For paired comparisons, run the same case through A and B, randomize presentation
order, blind the reviewer, and bind both outputs to the same input/checkpoint
manifests. Report call-level paired differences with a stratified call-level bootstrap
95% confidence interval, plus slice counts and failures. Use ablations for retrieval
off/on, reranking off/on, profile/judge off/on where permitted, and C2 reuse versus a
deliberately separate C2 run only as an engineering-cost comparison. Do not use an
aggregate weighted score to erase a severe safety or source-grounding failure.

## Proposed pilot gates

These values are proposed defaults for owner review. They are not official ZIP
thresholds, and they do not override the source-defined 95/100 public-score hold.

| Gate | Proposed pilot default |
| --- | --- |
| Lineage and isolation | 100% of successful artifacts bind the exact tenant, source hash/revision, checkpoint parents, recipe revision, and deletion state; any cross-tenant or stale-source read blocks the recipe. |
| Contract validity | 100% of published evidence references parse and match literal source text and authoritative timing; one invalid reference blocks publication. |
| Coverage | 100% of native transcript segments are covered exactly once by merged fact packets before judging; missing or overlapping chunk coverage blocks the run. |
| Severe unsupported claims | 0 in a candidate report; any severe unsupported allegation blocks promotion and creates a correction/rejection proposal. |
| Reliability | Proposed pilot minimum: 95% completed task attempts on development cases, with all failed/unknown attempts visible. This is a proposed operational gate, not a quality claim. |
| Pairwise usefulness | Compare point estimates and 95% call-level intervals; do not promote on a point estimate alone. Proposed exploratory signal: candidate lower confidence bound must not be worse than baseline on any critical slice. |
| Readability | Proposed exploratory target: at least 80% correct comprehension responses, with no critical evidence/uncertainty item below 70%; report item counts and reader mix. |
| Cost | Offline and auth-local runs must be ₹0. Future paid runs require a fresh quoted integer-paise budget and explicit approval; no automatic paid fallback. |
| Public reporting | Numeric 95/100 score publication remains withheld until the source-defined mismatch and coverage policy is approved. Internal benchmark intervals are not public accuracy claims. |

If a slice is underrepresented or fails, withhold or expand that route. Do not average
it into a passing global result. Threshold changes require a new frozen gate revision
and do not rewrite prior runs.

## Dual review and correction loop

Dipak's contextual lane reviews whether a finding is supported, applicable, useful for
the sales situation, and paired with one behaviorally specific practice action. The
lane can mark insufficient context or reject an inferred hidden objection. Suyash's
measurement lane reviews source channels, sample clock, units, compression/noise,
F0/overlap, extractor receipts, attribution, and whether the UI misrepresents a
measurement. A plot is not measurement certification.

Each review binds `tenant_id`, `run_id`, run revision, transcript revision, measurement
revision, and profile revision, plus reviewer assignment and evidence references.
Disagreement is preserved as an append-only proposal. A correction or rejection must
state actual, expected, reproduction steps, exact evidence, permission reference, and
an allowed `development` or `calibration` split. It becomes a fixture proposal, not a
gold label and not an automatic training example. Holdout corrections are forbidden
until the holdout is no longer sealed under a separately approved process.

Profile revisions, retrieval revisions, and judge revisions are explicit artifacts.
Promoting a correction or profile change invalidates the affected descendants and
creates a new run; it does not mutate old reports or silently retrain any model.

## Retrieval, deletion, and tenant boundaries

The optional retrieval/vector index is an evidence locator. It may improve recall and
ordering of permitted source spans, but it cannot alter C2 facts, create a training
label, update model weights, or authorize a report. Every indexed item carries tenant
ID, source ID, source revision, permission/retention state, and deletion tombstone
metadata. Query and rerank results are filtered by tenant and source revision before
the model sees them.

Deletion or revocation removes the item from retrieval, invalidates descendants, and
fences publication. A cached blob whose hash, source revision, permission, or
deletion state cannot be verified is unusable and cannot count as a successful result.
Recovery reconciles through the application repository and receipt chain. Operators do
not use direct SQL to repair state or mark a run successful.

## Release, rollback, and operator workflow

Promotion requires a frozen gate containing regression, development, calibration,
sealed-holdout, evidence-grounding, slice-safety, cost, latency, and rollback checks.
The candidate artifact, gate hash, every check receipt, and explicit approver/rollback
reference must match. Publication is a pointer to an immutable candidate; rollback
selects the prior approved pointer and records a new receipt. It does not overwrite
history, alter source data, or change provider billing state.

The following is a **proposed future SSH operator command shape**, included for
workflow design only. It is not an implemented command and must not be run until the
benchmark CLI, host, checkout, manifest, and approvals exist:

```powershell
ssh <approved-staging-host> "cd <approved-checkout> && `$env:AC_ALLOW_PAID='0'; `$env:PYTHONPATH='<checkout>/packages/python'; python -m <future-benchmark-cli> run --stage offline --manifest <manifest> --run-id <run-id> --receipt-dir <external-receipts>"
```

For the future restricted-staging stage, the operator would first present the exact
recipe, allowed case IDs, source permissions, provider terms, and integer-paise quote
for owner approval, then use the same run ID and an isolated staging receipt path.
The future command would set paid access only under that approval and would stop on a
missing/ambiguous receipt; it would never retry automatically or use another provider
to spend around a failed gate. If a CLI/API is unavailable, record `blocked` and fix
the implementation rather than issuing direct SQL.

## Current completion boundary

This plan authorizes only offline and authenticated-local synthetic benchmarking. It
does not authorize provider purchases, real recordings, staging, production, secrets,
or automatic training. The next approval artifact must freeze the dataset manifest,
recipe matrix, proposed gate values, review assignments, and zero-cost receipt path.
Only then may a later owner-approved task propose restricted-staging provider calls.
