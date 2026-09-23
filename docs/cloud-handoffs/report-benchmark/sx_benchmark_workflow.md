# Sales Xray independent benchmark workflow

**Status:** design and budget-neutral scaffolding only. No provider generations or benchmark results exist in these artifacts. This package does not change other implementation work or deploy anything.

## Files and offline commands

Place the JSON, corpus CSV and Python utility in the same directory. Python 3.10+; standard library only for the utility.

```sh
python sx_benchmark_offline.py check sx_benchmark_experiment.json
python sx_benchmark_offline.py example-cost
python sx_benchmark_offline.py summarize sx_benchmark_results_template.csv --arm-id v4_final --track audio_to_report --seed 20260923 --draws 10000
```

The last command on an empty template reports no observations, not zero cost or success. CSV booleans are `true`/`false`; an empty numeric cell means unknown. After unblinding, `consensus_pair_decision` is `candidate`, `baseline`, `tie` or `abstain`. Keep raw A/B reviews plus the protected assignment map in JSONL. Exactly one primary row per independent family/arm/track enters the primary endpoint. Secondary translations and repeats have `primary_render=false`.

`JSONL` records conform to `sx_benchmark_records.schema.json`. Records are run, attempt, claim_review, pair_review and cost_event. Schema validation must be followed by relational checks: lineage hashes, source ranges, immutable history, token accounting, split isolation and cost reconciliation. A syntactically valid record is not proof of report truth.

## Reviewer procedure and anchors

1. Curator creates private gold from audio/transcript with exact evidence spans, speaker uncertainty, material facts, critical corrections, expected unknowns, forbidden assertions and acceptable mission properties. There is no canonical 'perfect report' for the generator to copy.
2. A blind reader shows reports A/B in the same typography and common content structure. Source evidence remains available. No arm/model/prompt/cost identity until reviews lock. Native product layout usability is a separate task, not mixed into prompt-only content preference.
3. An appointed lead reviewer and an independent sales reviewer judge independently. Assign appropriate English/Hindi/Marathi competence to both input and output review. A third qualified human adjudicates disagreements; keep original ratings and reasons. Never treat the author of the candidate methodology as the sole oracle.
4. Check hard invariants before preference: quotations/source spans, semantic entailment, conditional commitments, corrected amounts, speaker uncertainty, and absence of invented sales, probabilities, recurrence or visual claims.
5. Rate each applicable dimension independently: semantic entailment, material coverage, context/role reasoning, coaching usefulness, language naturalness and report usability. 0=false/harmful/unusable; 1=major repair; 2=substantive gaps; 3=accurate/useful with only minor edits; 4=exceptionally clear and context-sensitive. N/A requires a reason. These are internal report-quality assessments, not salesperson scores.
6. Record A, B, tie or abstain. Tie means no material difference in practical usefulness, not uncertainty. Abstain means inadequate evidence, competence or comparability; explain it. Missingness cannot be silently discarded.
7. Auxiliary model judges see the same evidence and rubric, not model names, expected winner or private generator prompt. On at least 12 separately labeled calibration pairs, require >=80% human agreement, <=10% A/B order flips and detection of every severe trap. Otherwise remove model-judge influence and keep manual review. These are provisional thresholds, not a calibration guarantee.

## Expected invariants

- Exact quote matching proves transcript consistency, not that ASR heard the audio correctly. Track B checks audio independently.
- A valid citation to unrelated text does not support a claim.
- Preserve negations, exact names, money, dates, corrections and conditional commitments.
- Unknown, unobserved and not applicable are distinct from failure.
- Setter/discovery/follow-up objectives differ; medium is not purpose.
- A salesperson's suggested target is not a prospect's declared goal.
- Conditional willingness is not paid/won; do not invent revenue or probability.
- No mind-reading, fake urgency, manufactured ROI or pressure after a clear no.
- Give specific reinforcement and a consequential correction; not a longer list for its own sake.
- One actionable mission is conditional on adequate evidence; do not manufacture it in unusable audio.
- No persistent learner/mastery/journey claims from a single-call candidate.

## Pseudocode for the local implementation owner (not existing repo commands)

The names below are interfaces to implement against actual local adapters. Do not assume these functions already exist.

```python
spec = load_and_validate_manifest()
assert spec.namespace_is_isolated_from_other_work
assert source_sha == spec.candidate_sha
assert immutable_baseline.prompt_hash == expected_legacy_hash

# P0: always allowed locally; no dispatch or remote token-count endpoint.
verify_split_isolation_by_family_and_hash()
verify_gold_access_separate_from_generator()
for arm in spec.planned_arms:
    qualify_from_existing_local_adapter_metadata(arm)
    require_supported_schema_parameters_usage_normalizer(arm)
    resolve_price_and_policy_provenance_or_mark_unknown(arm)
    compile_input_and_chunk_plan_without_network(arm)
append_event("plan_created", manifest_hash, request_upper_bounds)

# Stop until a separate approval for the exact plan is recorded.
if not valid_owner_approval_for_exact_manifest():
    return BLOCKED_NO_SPEND_AUTHORIZATION

for call_family in preregistered_order:
    for arm in randomized_interleaved_pair_order(call_family):
        assert existing_provider_consent_retention_authority_allows(arm, call_family)
        inputs = allowed_inputs_without_gold(call_family, arm.track)
        stage_nodes = content_addressed_DAG(inputs, arm)
        for node in stage_nodes:
            if compatible_authorized_completed_artifact_exists(node):
                attach_reuse_and_original_cost_provenance(node)
                continue
            # Cache key includes input dependencies, stage algorithms, model/API,
            # schema, context, prompt, settings and language where relevant.
            with atomic_budget_transaction():
                require(known_spend + unresolved_reservations + node.upper_cost <= approved_cap)
                reserve(node.upper_cost)  # Not an actual charge.
                append_event("attempt_started", node, frozen_settings)
            try:
                response = existing_guarded_adapter.execute(node)
            except TransportUncertain:
                append_event("completion_and_cost_unknown", node)
                keep_reservation()
                stop_this_job_without_automatic_retry()
            else:
                append_private_usage_receipt_and_sanitized_event(response)
                normalize_usage_by_exact_endpoint_semantics()
                # Never double-count reasoning already included in completion.
                check_schema_and_reference_integrity(response)
                append_validation_state()
                if invalid:
                    use_at_most_one_preapproved_repair_OR_fallback_if_justified()
                    # No serial repair-then-expensive-fallback spending cascade.
        persist_immutable_benchmark_report_never_overwrite_production()

# Independent of generator; private gold is now readable by reviewers only.
for paired_report in blinded_review_queue:
    collect_independent_reviews_and_claim_annotations()
    retain_first_reviews_and_append_adjudication()
    lock_review_before_unblinding_cost_or_identity()

# Screening only at 6,12,18; sealed holdout only once, apart from safety abort.
if allowed_analysis_checkpoint():
    require_no_best_of_render_selection()
    aggregate_one_primary_observation_per_family()
    compute_stratified_paired_call_bootstrap_and_missingness_bounds()
    check_absolute_floor_and_language_duration_nonregression()
    summarize_known_costs_plus_unknowns_separately()
    reconcile_invoices_by_appending_receipts_not_replacing_attempts()
    emit(SUPERIOR | COST_EFFICIENT_ABOVE_FLOOR | INCONCLUSIVE | REJECT)
    # No automatic deployment/promotion.
```

## Append-only CLI design

Proposed CLI verbs, **not claims about current repo command names**:

`benchmark init`, `benchmark validate --offline`, `benchmark corpus seal`, `benchmark plan --no-dispatch`, `benchmark approval record`, `benchmark execute --approval-ref ...`, `benchmark review append`, `benchmark review lock`, `benchmark compare --at-checkpoint ...`, `benchmark cost reconcile --append`, `benchmark export --metadata-only`.

All use the same versioned service as Admin. They may not mutate production profile defaults or another task's schedule. Execution is disabled until authorized. Hash-chained events also need real append-only permissions; hashes alone do not prevent a privileged writer rewriting history.

## Cost and budget discipline

For each stage/provider/API tier use disjoint billed token categories, submitted channel duration and optional feature charges. Account for cache creation/storage, retries, provider-completed/application-invalid outputs, orphan requests, failed jobs and uncertain charges.

`variable_pipeline_cost = ASR + C4 + C5 + repair/fallback + incremental_worker/storage/egress`

`fully_loaded_pipeline_cost = variable_pipeline_cost + allocated_fixed_infrastructure/subscriptions`

`cost_per_unique_source_minute = all_attempt_cost / unique_original_seconds * 60`

`cost_per_accepted_report = all_attempt_cost / distinct_accepted_logical_reports`

Also calculate cost per report passing the quality floor. No accepted reports => undefined. Reusing ASR/C4 makes the *incremental experiment* cheaper but does not erase production-equivalent upstream cost. Shared receipts are booked only once in actual experiment spending.

`contribution = net_revenue_after_discounts_refunds_ex_tax - variable_pipeline - payment/refund_fees - variable_support - attributable_variable_acquisition`

`contribution_margin = contribution / net_revenue` when positive revenue is known.

`break_even_reports = fixed_allocated_cost / positive_contribution_per_report` under explicitly stated homogeneous-volume assumptions.

Net revenue, FX, nonrecoverable taxes, account discounts and support inputs are unknown. Do not claim profitable margins. Stress-test promotional expiry, two processed channels, lower cache hit rate, longer context, repair/fallback frequency and low utilization of subscription/VPS commitments.

## Acceptance of this package

The offline checker validates protocol shape and planned corpus counts. It does not validate candidate code, adapter readiness, model-generated report quality or real usage. Before spending, the implementation owner must resolve the capability intersection for a pure prompt-only comparison and approve thresholds, corpus, exact request count and funding cap. Preserve the no-deployment boundary throughout.

## Failure and sampling safeguards

All scheduled comparable jobs remain in denominators. Candidate-invalid/baseline-valid is a candidate loss; both invalid fail the acceptance floor. A severe error in an accepted report vetoes an arm. Caught invalid attempts remain first-pass failures and incurred/uncertain costs even after a successful repair. Deliberately unprocessable safety controls are declared separately in advance. Deduplicate repeated assertions when calculating claim precision; inspect all material claims, not only selected citations. Any retained synthetic fixture is a plumbing input until independently qualified for quality evaluation. Curator/actor/reviewer labor is a separate budget input, not assumed free.

## Publication caveat

All inherited model names, availability statements and list prices are provisional. Reverify primary documentation, API behavior, billing rules and account eligibility locally before authorizing an experiment. Cost examples are fictional arithmetic, not actual receipts. Private source references appear as citation identifiers only; no source passages or conversational requests are included.
