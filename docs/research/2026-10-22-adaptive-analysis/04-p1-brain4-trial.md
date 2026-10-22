# P1 dev trial: the one-pass C4 request v2 (with Brain 4.0) on AC dev calls, 22 Oct 2026

From the one-pass session. Orchestrator, 22 Oct 2026: "You may run the dev trial and refit within the same ₹40 cap I
approved (16 AC dev calls, Flex, no DB writes, ledgered on AUT-2177)". Then, after Flex refused: "Go with (a): run v2 on
standard now, on about 9 of the 15 AC calls."

## Setup
- **Calls:** the AC workspace's 21 Oct one-pass trial calls, 15 distinct recordings. Each was read over its stored
  Gemini 3.1 Flash-Lite transcript, and each was admitted before and after its request.
- **Request:** production's own v2 request (`stage.prompt(recipe=one-pass-facts-v2)` through
  `gemini_tasks.prepare_gemini_body`), Gemini 3.8 Flash, thinking LOW, 16,000 output tokens.
- **Checks:** `analysis.map_publish` and `brain4_part.parse`, as `plan_publish` does.
- **Nothing written:** no database writes, nothing stored at the provider.
- **Log:** numbers and ids only.

## Flex was unavailable
- From 14:44 UTC, Gemini 3.8 Flash on Flex refused everything:
  - five requests got an immediate HTTP 503 (UNAVAILABLE), with no usage, so not billed;
  - one request timed out after 300 s.
- At 14:50, a trivial "say ok" probe also got 503 on Flex, while standard answered it.
- So it was Google's Flex capacity, not our request.
- A Flex profile in production would have fallen back to standard for every call in that window.

## Results on standard (8 calls, 3.4–19.5 min, 71.8 audio min; shortest first to the ₹40 hard stop)

| | Result |
|---|---|
| Contracts (call data, notes, review) | **8 / 8 calls, every check ok** |
| Brain 4.0 part | **8 / 8 parsed**, 16–17 of 18 dimensions rated per call, no rule adjustments |
| Output tokens | 5.9k–7.0k (mean 6.3k). v1 measured 4.3k–4.9k on three of these calls (21 Oct cost measurement, over their Scribe transcripts): **about +1.6k–2.1k for Brain 4.0** |
| Input tokens | 9.9k–28.2k (Brain 4.0's instructions add about 5k) |
| Cost per call, standard | ₹2.94–4.54; **₹0.402 per audio minute** for C4 on these calls |
| Latency | 46–58 s (median 49 s); v1 Gemini C4 measured 37–50 s |

**Brain 4.0 answers:**
- Applicability: 132 applicable, 8 not enough evidence, 4 not applicable.
- Ratings: 2 ×4, 3 ×22, 4 ×59, 5 ×47. They lean high: 80% are 4 or 5.
- No gold judgement was made here. That is the AC-SVAL path (`brain4_eval`), and the block stays beta.

**Pointer review against today's review** (195 pointers scored by both):
- Raw lean: **+6.1** (sd 8.4); mean absolute difference 7.3.
- After calibration v1 (the Gemini table):
  - per-pointer lean **+1.5**, mean absolute difference 6.4;
  - overall lean per call **+0.4**, mean absolute difference 4.9.
  - v1's own leave-one-call-out fit was −0.5 and 5.5.
- Statuses agree on 131 of 216 pointers.
- **No refit.** Calibration v1 already brings v2 to within v1's own band. The +1.5 per-pointer residual can't be
  attributed to the Brain 4.0 part without v1 reads of the same calls: Flex was down, and the cap went to v2.
- **Re-check** with v1/v2 pairs when Flex is back, or from the first production v2 reads.

## What it means for the switch
- **Brain 4.0 inside the read adds about ₹1.0–1.1 a call on standard** (about ₹0.5 on Flex): about 5k input and 2k
  output tokens.
- The separate `brain4_shadow` read costs about ₹0.9–1.9 a call on standard (₹0.44–0.96 on Flex, gold-v1 reads).
- So v2 is **cheaper only where Brain 4.0 is shown** (AC today). For every other workspace it adds about ₹1 a call.
- Production's configuration is one per environment, so switching it to v2 makes every analysed call carry the part.
- **Recommendation:** switch to v2 when Brain 4.0 becomes the Report, the cost research plan's P2, not before. Until
  then, keep v1 and the shadow read for AC.

## Spend (dev Gemini key)

| Item | ₹ |
|---|---|
| Flex run (14:43): 5 × 503, not billed; 1 timeout, counted at its worst case | ≤ 4.98 |
| Flex/standard probe | about 0.00 |
| Standard run (14:52): 8 answered, priced from usage at list rates | 28.85 |
| **Total** | **≤ 33.83 of 40** |
