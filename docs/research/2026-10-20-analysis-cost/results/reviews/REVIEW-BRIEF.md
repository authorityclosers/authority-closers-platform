# Independent review: Sales X-Ray analysis-cost study (20 Oct 2026)

You are an independent reviewer. Another agent ran a study to cut the cost of analysing recorded Indian sales calls
from ≈ ₹1.19 per audio minute to ≤ ₹0.40 (tomorrow) and ≤ ₹0.10 (later) without losing quality. Your job is to
find what is wrong, weak or unsupported in its conclusions. Do not rewrite the study; review it.

Read, in this folder:
- `paper/` — the draft paper sections (01 cost anatomy … 08 next steps) and `costmodel.py`;
- `results/scores/*.md` — the measured benchmark tables; `results/ledger.jsonl` — every request with tokens and cost;
- `bench/calls/*/` — the fictional calls (script, facts, plan), `harness/` — the code that produced the numbers.

Check, with evidence (file + line or table row):
1. **Arithmetic.** Recompute the ₹/min of today's pipeline and of the recommended pipeline from the token fits and
   list prices. Do the numbers in the paper match `costmodel.py` and the ledger?
2. **Method.** Are the metrics valid for the claims? Look for leakage (a model judging its own family's output,
   ground truth that favours one arm), too-small samples, missing confidence intervals, synthetic-audio bias (TTS is
   cleaner than real calls), judge errors, and arms that were compared on different inputs.
3. **The recommendation.** Is the "≤ ₹0.40 tomorrow" pipeline really supported by the data, and does it respect the
   constraints (only providers already in use for real customer data; no production change without the owner;
   AC-SVAL: no official scoring changes)? What would flip the recommendation?
4. **The ₹0.10 path.** Is it credible? What is missing (provider gates, data residency, quality on real calls)?
5. **Anything the study missed** that a cost engineer would try first.

Write `review-<your name>.md` in this folder: a verdict line (agree / agree with changes / disagree), then numbered
findings, each with severity (blocker / major / minor), evidence and a concrete fix. Be concise. Do not call any
paid API, do not change any other file.
