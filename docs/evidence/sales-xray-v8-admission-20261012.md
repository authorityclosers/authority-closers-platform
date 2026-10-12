# New v8 outcome-prefix admission, 12 October 2026

The prior bounded diagnostic at `11c00be1` found that the candidate's outcome
enum rejects Won/Lost while generated summary prose still admits the exact
`The conversation ended as Won: ` / `Lost: ` prefixes. The first new regression
test reproduces this missing rejection before the repair (4.21 seconds).

New v8 admission now refuses that leading overall verdict in `pillars.summary`
and `pillars.outcome.line`, including case/whitespace variants and a sentence
ending instead of a colon. It rejects the candidate output rather than removing
or rewriting text. This is a narrow check for the documented assertion, not a
general classifier for every possible outcome claim or language.

Canonical reads retain the original saved text and canonical hashes, including
both old prefix forms. Literal source quotes are not scanned or modified;
an attributed quote inside a summary remains valid. Ordinary observations
containing "won trust" or "lost revenue" remain valid. Person-recorded outcomes,
their API/badges and the synthetic publication/supersession proposal are separate.

The semantic admission identity is now `ac.sales-xray.report-validator/13`.
The corresponding source fingerprint test is updated. The v8 prompt instruction,
marker, section mapping and spec pin are identical to `2d1197b6`. Provider schema,
qualitative-pack loader, activation gate, timing exporter and inspected native
input bytes remain unchanged. V8 still waits on AC-SVAL-01 Gate 2.

## Focused verification

- 184 candidate/legacy/report checks pass (4.65 seconds): explicit assertions
  rejected in both generated fields, the real C5 result adapter rejects both
  labels, saved text/hash round trips, ordinary observations and source quotes.
- 57 store/recovery/failure-detail checks pass (1.29 seconds), covering the new
  validator identity without changing retained content.
- Ruff, formatting, mypy for both source files, required API import and
  whitespace checks pass. No browser code changed.
- Fresh pinned retained comparison: 13/13 saved reports have identical admission
  and canonical content; 14/14 complete C4 inputs keep every source turn. One
  source exceeds 20 minutes. Two corpus entries lack saved reports and one lacks
  complete C4; missing inputs are not counted as passing reports/preparations.

The retained check is offline compatibility evidence, not new AI output or a
current dev latency measurement. There were zero provider calls, hosted writes
and manual deployments. Current dev timings and independent Gate 2 artifacts
remain outstanding under the existing operator handoff.

## Source and private receipts

| Source | SHA256 |
| --- | --- |
| Candidate admission/prompt | `735fbd22a1f815f4fe1ff8b87d71c7add8408f6cb57937ddb84522e1cf10b9a1` |
| Report parser | `16de4cd3e080ff179b2d1c03ab69df231be34ed64202675f43fd1d10def98b11` |

Private receipts under `/home/acdev/strikes/1801/` contain counts and pins only:

- `v8-prefix-admission-before-20261012.json`: original owned/protected source pins.
- `v8-prefix-protected-pins-20261012.json`, SHA256
  `79e86fda4d5dddd68bc6348578bd6c76e41c60091ba30856b47e5de853efc766`:
  nine unchanged inspected files and four unchanged prompt/spec assignments.
- `v8-prefix-admission-local-20261012.json`, SHA256
  `64b260c5f9a58d2de804833d8acdbf5aa85af06bff91aec61bec0db5888d6237`:
  source pins, first reproduction and 184-case local/static results.
- `retained-v8-prefix-admission-20261012.json`, SHA256
  `bfb6f6c8fb88b60b8c76207c2aef7d06d2ee2de21f6a3e2bb198c9f245843d54`:
  fixed pre-v8 baseline, distinct parser sources and stable retained inputs.

Earlier evidence and the runtime-package quality document remain unchanged.
New evidence stays in this docs path so evidence-only updates do not cause a
backend redeployment.
