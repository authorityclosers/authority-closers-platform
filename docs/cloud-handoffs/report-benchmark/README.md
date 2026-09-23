# Sales Xray report benchmark: sanitized public handoff

This is a publication copy of seven previously generated benchmark files, not a replacement application implementation or a set of benchmark outcomes. The original outputs remain unchanged outside this repository publication. The corpus is planned, the result CSV is empty, and external spending/provider execution remain disabled.

## Contents

- `sx_benchmark_experiment.json`: matched-track protocol, internal quality rubric, source citation locators, provisional rate-card inputs, cost/lineage/settings and stopping contracts.
- `sx_benchmark_records.schema.json`: run, attempt, claim-review, pair-review and cost-event JSONL structures.
- `sx_benchmark_results_template.csv`: header-only result template.
- `sx_benchmark_corpus.csv`: 18 screening and 36 holdout planning rows, no recordings or gold.
- `sx_benchmark_budget_template.csv`: unfilled stage budget worksheet, zero authorization.
- `sx_benchmark_workflow.md`: generic reviewer and append-only workflow, proposed interfaces, not installed app commands.
- `sx_benchmark_offline.py`: original standard-library checker, fictional cost arithmetic and descriptive call-level summarizer.
- `test_protocol.py`: synthetic offline utility tests.
- `TEST_RECEIPT.json`: commands, toolchain and results actually observed during transfer preparation.
- `MANIFEST.json`: publication paths, bytes, SHA-256 and original-file derivation metadata.
- `MANIFEST.sha256`: detached checksum; manifest and checksum exclude themselves from the payload entries to avoid circular hashing.

## Reproduce offline

Use Python 3.10 or newer without optimization (`-O` disables assertions in the original checker). The utility uses only the standard library. The test suite additionally uses `jsonschema`; the exact tested version appears in the receipt.

```sh
python sx_benchmark_offline.py check sx_benchmark_experiment.json
python sx_benchmark_offline.py example-cost
python sx_benchmark_offline.py summarize sx_benchmark_results_template.csv --arm-id v4_final --track audio_to_report --split holdout --seed 20260923 --draws 10000
python -m unittest -v test_protocol.py
sha256sum -c MANIFEST.sha256
```

These commands do not invoke providers. `example-cost` is fictional arithmetic with inherited provisional prices. An empty result file yields no observations, not measured zero cost or successful reports.

## Boundaries and unresolved assumptions

A passing synthetic protocol test is not a model-generated report outcome, a test of the application validators, or blinded human sales/language evaluation. The utility does not implement a provider runner, enforce all relational constraints, reconcile invoices or compute automatic promotion. The JSON schema validates structure, not semantic truth or authorization. Prospective runtime controls must use the application's actual guarded adapters and shared Admin/CLI registry.

All inherited model identifiers, current-availability statements, language-support notes and list prices are provisional until locally checked against current primary documentation and account eligibility. Historical retrieval notes are not fresh verification during publication. No credentials, provider activation, data-policy opt-in, spending or deployment is authorized here. Statistical thresholds remain provisional; no superiority, profitability or universal accuracy is claimed.

No recordings, transcripts, prompts, private source passages, account receipts, personal reviewer identities or customer information are included. Authorized private document IDs and numeric locators are retained only as citations; citation access does not authorize redistribution of their contents. Public source links are research references, not executable endpoints.

Sanitization removed private operational history and source-reading narrative from the experiment and generalized named reviewers/task references in the workflow. The original utility and three CSV files are byte-identical to their original generated files. The JSON schema is whitespace-compacted with identical parsed structure. Methodology and provisional thresholds are retained, not silently retuned. The original files' hashes are recorded in the manifest; no private originals are committed.

## Retrieval and change scope

The handoff is restricted to `docs/cloud-handoffs/report-benchmark/` on one documentation branch based on `eb4d6ac48173d82efa9ca24ec15696a686465027`. Use the final immutable commit, not a moving branch, when validating hashes. No app source, workflow definitions or production defaults are changed. No pull request, merge or deployment is part of this handoff.

Known utility limitation observed in this transfer: the original checker/summarizer emits ResourceWarning messages for unclosed CSV readers at lines 28 and 92 under unittest warning settings. Tests pass; the original utility is intentionally unchanged. Use explicit file context managers in a separately reviewed maintenance revision. The descriptive summarizer is not the full release-gate evaluator.
