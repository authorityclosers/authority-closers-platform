# Decision experiments, 29 October 2026 (MP14 and MP15)

Internal operator tools only. No app wiring, deployment, seller scores, external AI calls or spend.
Only Authority Closers (02150758-5316-46bb-975b-4cd0f0041df2) and Estate Autopilots
(full UUID beginning 62562d4d supplied from the logged extract receipt) are eligible.
The CLI refuses an entire mixed-tenant input. No other customer's data may be used.
Analytics/lake training is disabled pending owner approval of the new privacy notice.

## Run on ac

```
uv run python -m ac_platform.decisions call_classifier \
  --input /path/to/call_classifier.jsonl --cutoff 2026-10-25T00:00:00Z \
  --provenance /path/to/receipt.json --output /private/local/results
```

Use `junk` or `next_best_lead` for the other two tools. Add `--ea-tenant FULL_UUID`
only when the extract receipt verifies that UUID. Run under the internal operator's
OS account. Files are local and private, not served over HTTP. The CLI prints aggregate
metrics and writes JSON probability-model parameters and evaluation results. No pickle.
Do not run under a shared public web endpoint. Model artifacts are experimental.

The receipt is JSON with `source_kind: "owner_crm"`, `query_log` (path to the logged
read-only query receipt), and `sha256` of the JSONL bytes. This is a provenance check,
not a substitute for the operator reviewing the logged extract's purpose and scope.

Each JSONL row has exactly `tenant`, `lead` (pseudonym), `event` (unique snapshot/event
pseudonym), `at` (feature snapshot time), `label_at` (when label became available),
`label` (integer 0 or 1), and `features`. Timestamps include timezone. Never send
names, phone numbers, email, raw call text, seller IDs, scores or analytics fields.
Only these numeric feature names are accepted:

| Model | Features available at prediction time | Positive label | Comparator |
| --- | --- | --- | --- |
| Junk | attempts, failed_attempts, days_since_connected, age_days | Later junk status, or later lost status after at least three independently failed attempts | At least three failed attempts |
| Next best lead | attempts, failed_attempts, days_since_connected, hour (UTC) | This attempt connected, from an independent CRM outcome | Fewest previous attempts first |
| Call classifier | duration_seconds | Independent explicit connected outcome | Duration above seven / eight seconds |

These are experiment comparators, not assertions about current app policy. Outcome is
a target for the call classifier, never an input feature that simply gives away the
answer. Do not label connection from the very duration rule being tested. Reject
ambiguous statuses rather than invent mappings. Document source outcomes and coverage.
Junk is not the same as all lost leads: a business rejection without failed contact
is not a dead number. Pick a fixed future observation horizon (suggested seven days)
and exclude immature/censored labels. Negatives need observation through that horizon.
Snapshot features must use events strictly before `at`; exclude the labelled attempt.
Never infer historical terminal timestamps from a lead's current state or updated_at.

No prior connection: `days_since_connected` uses a documented sentinel of 365,
not a made-up connection. A feature extraction receipt must record that convention.
Do not pool dev copies with production: use production as primary, dev fixtures apart;
dedupe by original event identity. Input snapshot IDs are unique within a tenant.

Train snapshots and their labels must both predate a frozen cutoff. Later snapshots
are test. Purged late labels are counted. Bins, probability threshold 0.5 and model
family are fixed before test. Both training classes and a later test set are required.
A Laplace-smoothed categorical naive Bayes model runs on local CPU with the standard
library, avoiding new dependencies. Model probabilities are not yet externally calibrated.
Duration thresholds seven/eight are compared on train only; both test results remain visible.

Evaluation gives precision, recall, Brier loss, lead-cluster bootstrap 95% intervals
(300 replicates, fixed seed), counts and measured latency in ms. Undefined precision
or recall is null, never zero. Next-lead ranking additionally reports precision/recall
among the top five attempted candidates per tenant/hour, one attempt per lead/hour.
This retrospective set cannot estimate lift among all open leads. Seller selection,
missing outcomes and hour coverage bias it. Whole-lead bootstrap preserves dependence;
very small or single-class samples cannot justify promotion.

## Model cards

| Model | Seller-facing purpose if later approved | Current use and limits |
| --- | --- | --- |
| Junk v0 | Suggest checking a likely dead number before another attempt | CLI only; never auto-close/delete. Needs time-stamped terminal labels and negative follow-up horizon. Lost does not automatically mean junk. |
| Next best lead v0 | Order eligible leads by estimated chance of a connection at this hour | CLI only; seller taps. Historical attempts are selected, not random. No claim of causal lift; no seller identifiers. |
| Call classifier v0 | Suggest whether a logged call connected | CLI only; no quality or seller rating. Explicit independent outcomes needed to calibrate ring-only durations. Duration is device/provider dependent. |
| Answer router v0 | Offer the closest approved answer, or abstain | Character TF-IDF embeddings and cosine threshold 0.65; local fixtures only. Await Dipak's 500 approved Q&A and disjoint threshold-validation/test sets. Lexical similarity is not semantic understanding. |
| Stage predictor | Suggest a lead stage | Not trained; requires owner-approved stage definitions and time-stamped stage transitions. Compare against keep-current-stage. Macro F1/confusion matrix and lead-cluster intervals. |
| Spend risk | Warn of likely wasted analysis spend on a call | Not trained; needs call-level cost, deduplicated job lineage and approved useful-outcome labels. Compare against duration-only skip rule; measure wasted INR and missed useful calls. No access/payment decisions. |
| Stage-of-the-day | Suggest today's stage/activity for a lead | Not trained; needs owner definition of target/horizon. Compare against last known stage, measure macro F1 and calibration. No person/workday productivity score. |

Every fitted model's evaluation JSON is its data/metrics appendix: source hash, cutoff,
train/test/purge counts, thresholds, intervals and latency. No official AC-SVAL score.
The AC-SVAL interim source (`docs/research/2026-10-21-brain4/AC-SVAL-REPORT.md`)
confirms that absent independent gold labels must be reported honestly, not substituted
with previous AI output. Fixtures test software; they are not CRM accuracy evidence.

## Draft privacy notice (owner approval required)

Proposed version: `sx-product-analytics-2026-10-29-v4`. Status: draft, not effective.
Retain v3's collected-field, masking, provider, retention and opt-out paragraphs and add:

> When product analytics is on, we also use pseudonymised usage records to train and
> test models that help improve Sales X-Ray's suggestions and reliability. These models
> do not rate or rank sellers as people, or decide access, payments or plans. Product
> analytics does not collect call content, transcripts, lead names, phone numbers or
> email addresses. You can turn this use off in Settings, Privacy; a workspace owner
> or admin can turn it off for the workspace. Raw analytics records are kept for 180 days.
> This notice does not authorise training on recordings, transcripts or CRM content;
> those uses require their own approved purpose and data controls.

Before activation: owner approves final words/version and effective date, ensure all
surfaces show it and opt-outs govern eligible rows, record notice provenance per row,
and define artifact deletion/retraining on withdrawal. Do not retroactively deem older
lake records eligible. v4 does not itself approve broader tenant training. This task's
CRM work relies only on the owner's explicit AC/EA order.

## MP15 dataset and evaluation plan

Inventory must count deduplicated paid successful analyses, distinct source calls,
languages, known duration minutes, unknown-duration calls, failures/retries and actual
paid costs separately. A paid job is not necessarily a usable transcript-label pair.
Inventory is aggregate-only; do not copy real content to external AI or this repo.

One local teacher-student record: owner tenant, pseudonymous lead/call/job IDs,
recorded_at, analysis_at, capture/source version, language/code-switch flags, notice
and consent/retention provenance, input hash/redaction version, teacher provider/model/
prompt/schema/version, paid-success lineage, validated structured teacher outputs,
evidence spans, independent CRM outcome with timestamp/horizon, human correction and
review status. Exclude seller scores and chain-of-thought. No teacher output is gold
merely because it was paid. Reject erased/ineligible calls, leaked identity, empty
transcripts, unsupported evidence and duplicate/retried jobs. Keep only needed fields.

Split chronologically and keep each lead and duplicate recording in one partition;
never let a later analysis supply an earlier training label. Freeze an untouched test
set. Report Hindi, Marathi, English and code-switched strata separately. Candidate
students, based on publisher model cards checked 29 October 2026:

- [Qwen3-0.6B](https://huggingface.co/Qwen/Qwen3-0.6B): smallest multilingual candidate,
  Apache 2.0. Test bounded structured outputs with thinking disabled.
- [Gemma 3 1B IT](https://huggingface.co/google/gemma-3-1b-it): small text candidate;
  Gemma licence requires review before use. Do not assume Hindi/Marathi adequacy.
- [SmolLM2 1.7B Instruct](https://huggingface.co/HuggingFaceTB/SmolLM2-1.7B-Instruct):
  Apache 2.0 English control. Its English emphasis makes multilingual evaluation essential.

No model downloaded, trained or externally invoked for MP15. Candidate capability is
unproven on these calls. Compare an unchanged student, distilled student, teacher and
simple CRM/duration rules on the same held-out calls. Measure connected/outcome precision,
recall, macro F1, Brier loss, evidence fidelity and unsupported-claim rate; 95% intervals
clustered by lead. Measure valid-JSON rate, abstentions, per-language failure rates,
latency p50/p95 in ms, memory MB, CPU time and actual INR per usable call. Stage/quality
needs agreed independent human labels; no people scoring. Teacher agreement alone is
not outcome improvement. Promotion requires owner-defined targets and independent labels;
run as a suggestion shadow experiment before any app change.

Budget ASK ONLY: ₹10,000 per month for two months; ₹20,000 total ceiling. Month one
proposed allocation ₹6,000 bounded training/compute, ₹2,000 outcome-label review,
₹2,000 evaluation/storage; month two same ceiling, released only after month-one
measured results. Stop at each cap. These are proposed allocations, not vendor quotes
or permission to use API credits. No chargeable execution until owner approves after
capture is verified live with v1.8.0. Verify actual capture records, consent provenance
and usable pair counts; a version number alone is not capture evidence. This task spends ₹0.

For unlabeled current lead/call snapshots, the same operator can run:

```
uv run python -m ac_platform.decisions.suggest \
  --model /private/local/results/next_best_lead-model.json \
  --input /private/local/current-snapshots.jsonl --output /private/local/suggestions.json
```

Current snapshots contain `tenant`, `lead`, `event`, `at`, `features` only. The same
owner-tenant and feature restrictions apply. Output sorts next-lead suggestions by
probability, contains no seller identifiers, and requires a seller's tap. Do not treat
junk probabilities as automatic terminal statuses. Each input is capped at 20,000
snapshots and 16 MiB. Model state contains aggregate bin counts, not raw examples.
