# C4 grounding and hosted-call evidence — 2026-09-14

This note records the bounded C4 grounding repair and the one staging observation that motivated it. It contains no provider credential, transcript text, audio, raw response body, database DSN, or secret.

## Observed staging failure

- Release: `c437c1758d8a66ede0221f83fe787bb13de33c40`.
- Non-secret browser receipt: `D:\AC-authority-closers-release-audit\activation-20260914\staging-first-hosted-call-c437c17.json`.
- Source SHA-256: `6799c0c52727c98164a811374715d1c27990acad1838da59fd80467d177c9156`.
- The first C2 and two C4 chunks completed. The third C4 task reached the provider, saved a private raw response, and failed local validation with the stable code `report_evidence_quote_mismatch`. The raw response had usage metadata of 2,880 prompt tokens, 833 candidate tokens, and 3,713 total tokens. The reconstructed C4 input was 19,075 canonical bytes, 10,243 UTF-8 characters, and 17 segments.
- Raw response SHA-256 before erasure: `1f39a1c8f9dcd8e8f1bb7ed3449ad0430f4d9cec37c5dae683be5a4a64b0023f`.
- The raw response and transcript were not retained in this worktree. The recording was canonically erased by delete command `6c94df43-e607-49d8-8ede-6a3087078e7f` and erase job `e1fd370d-fe7f-4f47-a1d7-0a3dd4a1188a`; therefore the exact quote character difference cannot be established. This evidence does not claim that Unicode, whitespace, punctuation, translation, or provider timeout caused the mismatch.

## Repair contract

`reports.py` keeps explicit model quotes strict: a supplied quote must be a literal substring of the addressed segment, with the existing segment and timing checks. The compact C4 prompt now asks the model to return the covered `segment_id` and omit copied quote text. The server retrieves the exact canonical segment text and native timing from that ID when it fits the bounded 2,000-character evidence field. Long segments still require an explicit bounded literal quote. Unknown IDs and IDs outside the current chunk remain rejected. The normalized `ac.sales-xray.style-independent-facts/1` packet shape remains unchanged for downstream consumers.

## Validation

- Focused C4/report/inference tests: 25 passed.
- Ruff check: passed.
- Targeted mypy for `reports.py` and `inference_tasks.py`: passed.
- Root's independent full conversation validation after the verified native preflight: 705 passed, 17 skipped. Receipts: `D:\AC-authority-closers-release-audit\activation-20260914\c4-grounding-and-diagnostics-unit.xml`, `D:\AC-authority-closers-release-audit\activation-20260914\c4-grounding-environment-retest.xml`, and `D:\AC-authority-closers-release-audit\activation-20260914\c4-native-preflight-retest.xml`.

## Budget state at erasure

Scope `11620b74-7e36-4f8a-8e4c-faf336c42888` had a 10,000-paise (INR 100) cap. The read-only account snapshot showed four uncertain provider holds totaling 2,600 paise (C2 1,100 plus three C4 holds of 500 each), no reserved or in-flight holds, one settled local reservation at zero actual paise, and 7,400 paise available. The held amounts are quote ceilings pending reconciliation; no actual invoice cost is asserted.

No provider call, retry, database mutation, erasure reversal, or runtime deployment was performed by this leaf.
