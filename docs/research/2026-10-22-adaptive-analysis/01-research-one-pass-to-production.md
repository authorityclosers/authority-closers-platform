# The research one-pass in production: gaps, shortest path, cost and accuracy (22 Oct 2026)

From the cost-research session, for the orchestrator. Measured numbers only; every projection names its inputs.
Nothing here changed production. The one-pass session (local_5f590df6) owns production routes and seals.

## 1. What "the research one-pass" is, and what production already runs

| | Research one-pass (cost research) | Production one-pass (live, revision 10) |
|---|---|---|
| Transcript | Gemini 3.1 Flash-Lite, JSON segments | the same model on the sealed C2 route `gemini-flash-lite-c2` |
| Analysis reads | **one** Gemini 3.8 Flash read: facts, 27 pointers, a short report; variants add the 18 Brain 4.0 skills and 10–20 coach notes | **two**: the one-pass C4 request (call data, notes, the 27-pointer review; recipe `one-pass-facts-v1`), then today's C5 report (coaching-v5) |
| Brain 4.0 | inside the same read (research variants) | a separate `brain4_shadow` Gemini read, for Brain 4.0 beta orgs (AC only today) |
| Output contract | research JSON (own fact types, own report shape) | the product's wire contracts: C4 fact packet, call objects, pointer review, C5 coaching-v5, brain4-review/1 |

**Correction to the brief.** Gold v1's "one pass (research build) 72%" is the research one-pass **without** Brain 4.0
(arm `onepass2`: exhaustive-facts prompt, 27-pointer review, Gemini 3.8 Flash; `gold_v1.py` reads
`text/onepass2/google_gemini-3.8-flash`). The research Brain 4.0 prompt on Gemini scored 60%.

## 2. Why it isn't on: the gaps, from the production code (workbench 4643dd63)

1. **Contract.** The research JSON does not match any production decoder:
   - Its facts use research types, not the call-data taxonomy (`extraction.validate_response`).
   - Its pointer objects lack the review's `outcome`, `buyer_qualification` and `prospect_profile`
     (`pointer_review.parse_review`).
   - Its report is not C5 coaching-v5 (`reports.parse_report_draft`), so the Report, the lead card and Admin cannot
     read it.
   - **Production already ported the idea in product formats:** that is the one-pass C4 recipe.
2. **Brain 4.0 is not in the production read yet.**
   - `one_pass/analysis.py` has no brain4 part: `stage_system_prompt()` is call data, notes and the review.
   - The hook exists: `brain4_shadow` says a review carrying its own `brain4` block wins on the Report, and that
     the shadow read fills in only for other calls; `brain4.parse` is the decoder.
   - The agreed v2 recipe (`one-pass-facts-v2`, c47d422d plan) has not landed.
3. **Transcript route: no gap.** It is the same Flash-Lite model.
   - The compact format was measured (−48% output on 6 fictional calls; −53% on 11 real calls), but the one-pass
     session kept JSON for −2.3 points of speaker accuracy.
4. **Caps and timeouts: no blocker.**

   | Limit | Value | Measured need |
   |---|---|---|
   | One-pass C4 output ceiling (`markers.MAX_COMPLETION_TOKENS`) | 20,000 | research single reads 5.3–8.4k output tokens; production facts 6.5–9.1k + Brain 4.0 1.5–2.5k |
   | C5 output ceiling | 8,000 | |
   | Every other stage | 4,000 | |
   | `brain4_shadow` output | 8,000 | |
   | Transport, standard routes | 180 s (`providers.MAX_STREAM_SECONDS`) | research single reads 36–54 s on 9–24-min real calls; production C4 13–50 s |
   | Broker (Flex) | 800 s; Flex window 300 s | |
5. **Measured pauses come too late.**
   - Production measures voice from audio frames only when it saves call data, after the read
     (`plan_publish.publish` → `deep_runner.measured`).
   - Feeding them into the read means measuring before C4.
   - Their measured value is evidence for D03; alone they did not raise coverage (36.7% vs 37.0%).
6. **Seals.** A recipe is bound to its route.
   - v2 needs new profile ids beside `gemini-one-pass(-flex)` and `luna-c4-one-pass(-flex)` in `c2_route.py`, and a
     seal-script flag.
   - `completion_ceiling` and `markers.is_one_pass` key on the v1 recipe and marker, so both need extending.
   - Then a Root seal, and an Align switch (`one-pass-flex-production.py`, which needs a recipe option).
7. **Calibration.**
   - `one-pass-pointer-calibration/1` (Gemini) and `-luna/1` were fitted on the v1 prompt.
   - Adding a Brain 4.0 part can move the review, so a refit is needed (the v1 trial measured 16 dev calls).
8. **The Report.**
   - Brain 4.0 becomes the Report in the next release (Brain 4.0 session, Slice A/B).
   - C5 still runs on every analysed call until the owner decides on C5 on demand.
9. **AC-SVAL.** Brain 4.0 stays Beta (`status: beta`); no official score before the gates.

## 3. Shortest path

**P1: Brain 4.0 inside the production one-pass read (recipe v2).** This is the one-pass session's agreed next
recipe; my measurements support it, and I am not building it.
1. `one_pass/analysis.py`: `stage_system_prompt()` + `PART brain4` (`brain4.part_instructions()`), `stage_schema()`
   + `brain4.response_schema()`.
2. `plan_publish`: `review["brain4"] = brain4.parse(answer["brain4"], segments)`, with its own check code. A
   failure never drops the review.
3. `markers`: `RECIPE = one-pass-facts-v2`, a new MARKER; `completion_ceiling` accepts v2.
4. `c2_route`: profiles for v2 (Gemini standard and Flex; Luna C4 later); seal-script flag.
5. A dev trial on the AC calls: contract pass rate, Brain 4.0 parse rate, review drift (calibration refit), latency.
6. Root seals, Align switches. The shadow read stops by itself for calls that carry a block.

**P2: C5 on demand once the Report is Brain 4.0.** This is the money (§4). It is an owner decision; "Get full report"
and per-seller levels already exist.

**P3: Flex and Luna,** already on the one-pass session's path. Option A (Gemini Flex) is sealed in production;
Luna C4 waits on Root (AUT-2179, AUT-2180).

**Not recommended: porting the research JSON itself.**
- It would need new decoders for C4, the review, call data and C5.
- It has no measured accuracy gain (§5).

## 4. Projected ₹ per audio minute on production's real mix

**Inputs, all measured:**
- **Mix:** 62 calls, 284.4 min, 14 days, canaries out. 27 are under 1 min and get the transcript and lead details
  only; 35 are analysed.
- **Per-stage rates:**
  - one-pass C4 fit: input 3,579 + 649/min, output 3,379 + 101/min tokens;
  - C5 from production receipts by length;
  - C2: ₹0.233/min standard, ₹0.1175 Flex;
  - Luna C4 on Flex: ₹0.19 + 0.0042/min per call.
- **Brain 4.0 part:** instructions measured at 20,508 characters (about 5.1k tokens); answer 1.5–2.5k output tokens
  (gold-v1 reads: ₹0.44–0.96 a read on Flex).
- **Prices:** list rates at FX 100. Script: `mixproj.py`.

| Production set-up | ₹/min all-in |
|---|---:|
| S0 today: one-pass v1 + C5, Gemini standard | **0.709** |
| S1 today + the separate Brain 4.0 read on every analysed call | 0.872–0.918 |
| S2 Brain 4.0 folded into the one-pass read (v2), C5 kept | 0.826–0.872 |
| S3 v2, C5 on demand (the Report is Brain 4.0), standard | 0.621–0.667 |
| S4 S3 on Flex | **0.311–0.334** |
| S5 v2 on Luna (facts + Brain 4.0), Flex, C5 on demand | **0.153–0.156** |
| S6 S5 + compact transcript | 0.112–0.115 |

- **Folding Brain 4.0 saves only the transcript's second read:** ₹0.08 on a 2-minute call (₹1.21 separate against
  ₹1.13 folded) and ₹0.71 at 15 minutes (₹1.84 against ₹1.13). That is about ₹0.046/min on this mix.
- **C5 is ₹0.205/min of this mix.** Each 10% of calls that tap "Get full report" adds ₹0.021/min back.

## 5. Accuracy: what is measured, and what is not

**Measured, real calls.** Six calls carry the coaching lead's notes; all on the same Flash-Lite transcripts:

| Pipeline | Gold v1: agreement with his 43 labels (95% CI) | His 81 notes covered (Haiku + Luna judges) |
|---|---|---|
| Classic (today's pointer review) | 64% (49–77) | 46.0% |
| Research one-pass, `onepass2`, Gemini | 72% (57–83) | 45.7% (−0.3 [−7.1, +8.1]) |
| Research Brain 4.0, Gemini | 60% (44–73) | 43.2% |
| Research Brain 4.0 + measured pauses + coach notes, Gemini | — | **50.0% (+4.0 [−1.8, +10.5])** |
| Product Brain 4.0 prompt, Gemini | 55% (38–70) | — |
| Product Brain 4.0 prompt, Luna | 39% (28–50) | — |
| Research Brain 4.0 + coach notes, Luna | 40% (26–56) | 40.7% (−5.2 [−10.8, +1.1]) |

**Measured, 16 fictional calls** (the product's full formats, three subscription-judge runs averaged):
- Luna facts 72.1% against today's 63.5% (+8.8 [−3.1, +18.9]).
- Coaching −3.1 [−11.4, +4.2].

**What it supports.** No pipeline is shown better than another: every interval overlaps. The defensible claim is
"equal within noise, cheaper".

**Not measured:**
- The production one-pass v1 on gold v1. Its review was never scored there.
- The v2 read's drift on the review.
- Accuracy on the real mix at all. Its first real measurement is the blind 18-skill checkpoint: 25 calls for a
  first read, 50 for Gate 3.

**Cheapest next measurement.** Production's exact v1 and v2 requests on the 7 gold calls: about ₹5–10 on the dev
Gemini key. It needs your go-ahead, because those calls are outside the AC-workspace trial approval.

## 6. Can the same read fill Brain 4.0's 18 skills, dropping the separate read? Yes.

- **Measured.**
  - Research single reads returned facts, all 18 skills and a report in one Gemini call on 7 of 7 real calls:
    44–54 s, 5.5–8.4k output tokens, under the 20k one-pass ceiling.
  - The product's own Brain 4.0 prompt passed its contract on 21 of 21 gold reads.
- **Code.** The Report already prefers an inline block, and the shadow read already skips such calls.
- **Saving.** ₹0.08–0.71 a call (§4), ≈ ₹0.046/min on the mix. The skills' output is paid either way.
- **Risk.** The review may move with the longer prompt: refit the calibration in the v2 dev trial before the seal.
