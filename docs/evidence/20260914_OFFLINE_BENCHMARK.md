# Executed offline context/profile comparison

Source base: `a67a0cf`. This independent leaf is not part of the frozen staging
candidate. It replaces the benchmark plan's nonexistent CLI placeholder with an
executable synthetic context/profile recipe, using the existing context, review
partition and checkpoint hashing primitives.

The package implementation-plan slices 4 and 5 and calibration offline stage were
read again for this work. Current AC/user gates remain authoritative. No attached
real-call recording, transcript, key, review feed or holdout content was opened.

## What changed

- Strict metadata-first admission, development/calibration selection and source/
  participant leakage checks; holdout has metadata only and no path.
- Bounded local fixture IO and closed adapter selection; no subprocess, provider,
  database or training operation.
- One context reduction per case, detached per-candidate copies, exact fixture
  expectations, declared rejection stage and failure receipts instead of a score.
- Real local timings, candidate/input/implementation hashes, exclusive UUID run
  directories, JSON receipts and a readable comparison report.
- Eight explicit fixtures, including Hindi/English and Marathi literal text, two
  research candidates, no human-quality or language-accuracy claim.

See the [contract and flow diagram](../contracts/SALES_XRAY_OFFLINE_BENCHMARK_V1.md).

## Executed tests and experiment

Windows, project Python 3.12 runtime; current source modules imported via
`PYTHONPATH=packages/python`. Final invocation:

```powershell
python -m pytest tests/unit/conversation_intelligence/test_benchmark.py `
  tests/unit/conversation_intelligence/test_context.py `
  tests/unit/conversation_intelligence/test_review.py -q --tb=short `
  --basetemp=D:/AC-authority-closers-release-audit/offline-benchmark-tests-20260914-final `
  --junitxml=D:/AC-authority-closers-release-audit/offline-benchmark-20260914-final.junit.xml
```

**68 passed, 0 failed, 0 skipped in 2.39 seconds.** Includes the existing context
and review regression subsets, not 68 new tests. Tests also inject a mutating
profile and wrong expected boolean to prove the runner detects failed behavior,
refuse altered digests, reject partition leakage and wrong rejection stages,
exercise immutable output collision/incomplete receipts, and deny nonregular files
before opening. The core runner test replaces socket construction with a failure.
Scoped Ruff/format and strict mypy for both new source modules passed.

Executed the real CLI, outside pytest, using the checked-in fixture manifest:

```powershell
python -m ac_platform.conversation_intelligence.benchmark_cli `
  --manifest tests/fixtures/sales_xray_offline_benchmark/manifest.json `
  --receipt-root D:/AC-authority-closers-release-audit/offline-context-benchmark-20260914 `
  --run-id c4ec2492-7828-4d9f-b8d5-e5f8c6d4d962
```

Exit 0: **16 comparisons across 8 cases passed their declared expectations**,
including intentional rejections. Eight input files were read, eight context
reductions attempted, fourteen per-case profile projections attempted (two
comparisons stop at the deliberately invalid context). Provider/ASR calls: **0**.
Provider cost: **₹0**. There is no model-quality result or promoted candidate.

Candidate-only nearest-rank p50/p95 under Python allocation tracing:
source-profile-full **6.249 / 7.070 ms**; wording-fixture-bounded
**5.744 / 16.355 ms**. Context time is separate. These tiny local fixture timings
do not measure hosted full-call delivery or support a speed promise.

[Machine receipt](offline-benchmark-20260914/comparison.json),
[readable comparison](offline-benchmark-20260914/comparison.md),
[JUnit](offline-benchmark-20260914/tests.junit.xml) and
[file hash index](offline-benchmark-20260914/receipt-index.json) preserve the result.
The original run directory remains outside Git. There is no browser/UI/deployment
change in this leaf.

## Failures retained and resolved

The first pytest invocation passed 65 tests but had two setup/teardown errors for
one oversized-byte parameter: pytest embedded its 1 MiB value in
`PYTEST_CURRENT_TEST`, exceeding Windows' environment-variable size limit. Added
short explicit parameter IDs; no product bound or assertion was relaxed. The
next run passed 66 checks; the final run adds incomplete-output/nonregular-file
coverage and passes 68. Earlier logs stay outside Git, and failed runs are not
counted as passes. An initial Ruff warning on an absolute temporary-path rejection
fixture was corrected by using another absolute fixture path.

## Status

Implemented and tested locally. Provider-tested: no provider adapter in this recipe.
Staged: no. Production-published: no. Full model benchmarks, real calibration data,
authorized reviewer imports, human usefulness labels, Admin execution controls and
promotion remain open parts of the goal. This leaf changes no active release.
