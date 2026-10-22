# AC-SVAL report: Accuracy Brain 4.0 against the coaching lead's gold set (interim, 21 Oct 2026)

**Status: interim, and the gold set is empty.** The owner approved a labels-only read of production on
21 Oct 2026. It ran at 09:07–09:12Z (log: shared notes, `brain4-prod-query-log-20261021.md`) and found **no
gold judgement on any environment**: production has 61 calls assigned to the coaching lead (18–19 Oct) and 0
saved answers ever (`conversation_gold_rows`, erased rows included), 0 Review 2.0 verdicts and 2 old-style
review labels; staging and dev have none either. So there is nothing to measure Brain 4.0 or today's pointer
review against yet. This report has the method, what a gold set like this can and cannot decide, Brain 4.0's
behaviour on the 16 fictional calls, and how the numbers fill in once answers are saved. Gates are from
AC-SVAL-01 §12; its thresholds are "engineering starting points", reported with intervals and counts.

## 1. Recommendation (per dimension)

| Dimension               | Official now? | State                      | Why                                                                                                                                                                                          |
| ----------------------- | ------------- | -------------------------- | -------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- |
| D01–D18, all            | **No**        | **Beta**                   | Gate 0 not met (one rater, no blinded second rater); gold labels judged pointers while seeing today's AI answer; the compact rubric is not yet signed off by the coaching lead (ADR 0036 D5) |
| D03 Tone, Pace & Pauses | No            | Beta, mostly "–"           | The rubric needs audio; from a transcript it can only see problems, so the checker turns any rating above 3 into "not enough evidence"                                                       |
| D07 ethics gate         | No            | Beta, shown never averaged | FAIL needs evidence; the gate is shown beside the numbers                                                                                                                                    |

Nothing here becomes official by a code switch: `brain4_eval.readiness` returns "needs data", "beta" or
"Gate 3 candidate", never "official".

## 2. What the gold set is

The coaching lead's phone review (`/review`, live since v0.62; Review 2.0 since v0.69). For each of the 27
pointers of a call's AI pointer review he saves agree / partly / disagree, and optionally the right score or
status and why (too harsh, too generous, wrong status, …). Saves are append-only (a change supersedes); call
erasure empties them. Review 2.0 verdicts judge call data objects, facts, moments and coaching, not scores, so
they do not enter this evaluation.

## 3. Method (implemented: `brain4_eval.py`, Admin → Gold set → Brain 4.0 evaluation)

- **Labels.** A gold line's label is the band he endorsed: his score's band when he gave one, his status when
  he gave one, today's band when he agreed, and only a direction ("too harsh" = up, "too generous" = down) when
  he disagreed without a score. Skips are counted apart.
- **Comparison.** Each Brain 4.0 dimension is compared through the pointers that ask its question (README §2):
  rating 5 = excellent, 4 = good, 3 = average, 1–2 = needs improvement; "–" = not judged.
- **Metrics** (AC-SVAL-01 §9, ordinal rubric dimension): exact band, within one band, quadratic weighted kappa,
  mean band error and signed lean; judgeable-or-not agreement; direction agreement. Today's pointer review is
  measured on exactly the same lines.
- **Intervals.** 95% percentile bootstrap over whole calls (lines of one call are not independent), fixed seed.
- **Repeatability.** Repeated Brain 4.0 reads of one call (gold calls are read even when the review already has
  a Brain 4.0 block): share of dimensions with the same rating.
- **Gate 3 candidate** (formative, AC-SVAL-01 §12.4 targets): ≥ 50 gold calls, weighted kappa ≥ 0.70 with the
  interval's lower bound ≥ 0.55, within one band ≥ 90%.

## 4. Limits of this gold set

1. **One rater.** Gate 0 needs two independent expert ratings and their agreement first ("if experts cannot
   meet the threshold, block the rubric rather than blaming the AI").
2. **Not blind.** He saw today's answer before judging (§8.1 requires that raters not see the AI result). An
   "agree" makes today's band the gold band, so today's review is favoured in every comparison.
3. **Pointers, not dimensions.** Brain 4.0's dimensions are compared through the closest pointers; two pointers
   (Question to Talk Ratio, Call Control) have no dimension.
4. **Small and clustered.** Expect tens of calls; AC-SVAL-01 §14: 0 failures in 50 still allows about 6%.

## 5. Brain 4.0 on the 16 fictional calls (fictional only; bench key)

The product's Brain 4.0 part, exactly as the shadow read sends it, answered by GPT-6 Luna on OpenAI Flex
(bench key, store:false), 16 fictional calls × 3 independent reads, 21 Oct 2026. Script and summary:
`brain4part.py`, `fictional-summary.json` in this folder. No real call was used; Gemini's bench key is refused
(403), so the shadow read's own model (Gemini 3.8 Flash) is not measured here.

- **Contract:** 48 of 48 answers passed `brain4.parse`. None needed a checker rule: the model itself gave "–"
  for D03 every time and never a 5 without evidence.
- **Tokens and cost:** 9.5k in, 4.2k out per read (reasoning included); $0.057 for all 48, about ₹0.12 per read
  on Luna Flex.
- **How often each dimension is rated:** D03 never (as designed); D13 90%, D14 88%; every other 92–100%.
- **Repeatability** (three reads of the same call): the same rating in all three reads on 38–81% of calls
  (mean 56% over the 17 rated dimensions), within one point on 75–100% (mean 95%).

| Dim | same in 3 reads | within one | Dim | same in 3 reads | within one |
| --- | --------------- | ---------- | --- | --------------- | ---------- |
| D01 | 50%             | 94%        | D10 | 75%             | 94%        |
| D02 | 56%             | 100%       | D11 | 63%             | 100%       |
| D03 | all "–"         | all "–"    | D12 | 63%             | 94%        |
| D04 | 56%             | 94%        | D13 | 50%             | 81%        |
| D05 | 44%             | 100%       | D14 | 69%             | 100%       |
| D06 | 38%             | 100%       | D15 | 44%             | 100%       |
| D07 | 44%             | **75%**    | D16 | 50%             | 94%        |
| D08 | 50%             | 94%        | D17 | 69%             | 94%        |
| D09 | 50%             | 100%       | D18 | 81%             | 94%        |

**What this means:**

- One read is noisy at the one-point level: AC-SVAL-01 Gate 3 wants criterion flips under about 5% on
  semantics-preserving changes, and an identical re-read flips the exact rating on 19–62% of calls. Bands
  (needs improvement / average / good / excellent) and category means are steadier than single 1–5 ratings.
- **D07's ethics gate is the least stable judgement:** 17 of 48 answers rated it 1 (FAIL) and only 75% of calls
  stayed within one point. A FAIL must never reach a salesperson without a coach's review.
- Options before anything is official: average two reads (twice the cost), show bands instead of exact ratings,
  or both. These are the coaching lead's and owner's calls; the Report today shows the 1–5 rating labelled Beta.

## 6. What more gold data is needed

1. **Sign-off:** the coaching lead reviews the compact rubric (`profiles/brain4_compact_v1.txt`) and the
   pointer map (README §2), and picks a roll-up (README §4).
2. **Blind Brain 4.0 ratings:** a review pipeline where he rates the 18 dimensions 1–5 / "–" on a call without
   seeing any AI answer: at least 50 calls, with each dimension applicable on at least 30 of them (D11, D12,
   D15–D17 are often "–" on short calls, so sample discovery-to-close calls).
3. **A second rater** on at least 30 of those calls, blind to both, for Gate 0 (weighted kappa ≥ 0.70 between
   experts).
4. **Frozen set:** those calls frozen as the evaluation set; prompt changes measured on them before release
   (AC-SVAL-01 §13.1 shadow mode).

## 7. Filling in the production numbers

- **Answers first.** The coaching lead's corrections must be saved in `/review` (or, if he has been writing
  them elsewhere, for example on the Pulse review tasks, entered there); nothing else counts as gold.
- **Brain 4.0 reads, in place (approved, up to ₹300):** v0.75 (migration 0117) carries the shadow reads; Align 3
  sets `brain4_shadow` to ₹300 on production with `scripts/data-changes/ai-spend-cap.py` and the owner's words.
  The pointer review job then reads Brain 4.0 on each of the 61 assigned calls (one per idle pass, about ₹2 a
  read, about ₹120 in all). Nothing leaves production.
- **The figures** appear on Admin → Gold set → Brain 4.0 evaluation as answers are saved: acceptance of today's
  review per pointer, and Brain 4.0 against the endorsed band per dimension, with intervals and counts.

## 8. Checkpoint gold v1 (21 Oct 2026): the coaching lead's correction doc

The owner, 21 Oct 2026: "The doc I sent with corrections and audio calls are the only data Dipak gave, and
just use that and make it possible. Reviews on the app were never done."

**Gold v1** is that doc ("1. Language simplicity") on 7 real calls; 6 have notes. Of 81 numbered notes, 70 are
mapped to the Brain 4.0 dimensions they judge (`gold-v1-mapping.json`, note ids only: an inference for his
review); 11 are observations about the prospect or wording the rubric does not score. That gives 43 call-dimension
labels: 27 praise, 9 criticism, 7 mixed. His words and the calls stay in the research folder on ac (mode 700).

Scored offline (`gold_v1.py`, aggregates in `checkpoint-gold-v1.json`) against each pipeline's saved read of the
same calls, all on the same Gemini 3.1 Flash-Lite transcripts. Brain 4.0 rating 4-5 reads as praise and 1-3 as
criticism; pointer scores 70+ read as praise; a mixed label agrees with a middle reading.

| Pipeline                                                 | Agrees with the coach (95% CI) | Praise kept | Criticism caught | Mixed | Rated | Same on re-read |
| -------------------------------------------------------- | ------------------------------ | ----------- | ---------------- | ----- | ----- | --------------- |
| Today's pointer review (Gemini 3.8 Flash)                | 64% (49–77%)                   | 19/26       | 2/9              | 6/7   | 42/43 |                 |
| One pass (research build, Gemini 3.8 Flash)              | 72% (57–83%)                   | 22/27       | 2/9              | 7/7   | 43/43 |                 |
| **Brain 4.0, product prompt (Gemini 3.8 Flash Flex)**    | 55% (38–70%)                   | 11/19       | 1/8              | 6/6   | 33/43 |                 |
| **Brain 4.0, product prompt (GPT-6 Luna Flex), 2 reads** | 39% (28–50%)                   | 7/46        | 10/14            | 10/10 | 70/86 | 69%             |
| Brain 4.0, research prompt (Gemini 3.8 Flash)            | 60% (44–73%)                   | 16/26       | 2/9              | 7/7   | 42/43 |                 |
| Brain 4.0, research prompt (GPT-6 Luna)                  | 40% (26–56%)                   | 3/23        | 6/7              | 5/5   | 35/43 |                 |

The product prompt is exactly what the shadow read sends (`brain4_shadow.system_prompt`, `brain4.response_schema`,
answers checked by `brain4.parse`), run 21 Oct 2026 on the dev app keys under the owner's ₹300 Brain 4.0 budget:
Luna Flex 2 reads of all 7 calls (₹0.09–0.18 a read, store:false), Gemini 3.8 Flash Flex 1 read of 6 calls (₹0.44–0.96 a
read; the 7th call got "busy" twice on Flex and was not sent on the standard tier), **₹6.71 in all**. All 21 answers
passed the contract.

**What it says:**

- Every interval overlaps: on 6 calls no pipeline is shown better than another.
- The Gemini readers keep the coach's praise but catch almost none of his criticisms (1–2 of 9). Luna catches his
  criticisms (6 of 7) but agrees with his praise only 3 times in 23: it rates low across the board. Each model
  leans its own way, so a per-model display calibration (`brain4.Calibration`) is the lever once labels allow.
- Per dimension there are 1–6 labelled calls: no dimension can be graded, let alone made official.
- The product prompt behaves like the research prompt on the same model: Gemini keeps the coach's praise and misses
  his criticisms; Luna catches his criticisms and misses his praise, and repeats its own rating on re-read 69% of the
  time. Neither is closer to the coach than today's pointer review on these 6 calls.

**Can Gemini be made to catch the coach's criticisms?** (orchestrator, 21 Oct; same approved routes, ₹1.93 more,
₹8.64 of ₹10 in all)

| Variant                                                                            | Calls | Agrees with the coach (95% CI) | Praise kept | Criticism caught |
| ---------------------------------------------------------------------------------- | ----- | ------------------------------ | ----------- | ---------------- |
| Ensemble, mean of Gemini and Luna ratings (rule fixed before scoring; no new read) | 7     | 49% (33–64%)                   | 11/23       | 1/8              |
| Ensemble, Gemini capped at 3 where Luna's mean is 2.5 or lower (no new read)       | 6     | 55% (38–70%)                   | 11/19       | 1/8              |
| Gemini, product prompt (same 2 calls)                                              | 2     | 67% (39–86%)                   | 5/6         | 1/4              |
| Gemini, product prompt + a "find what went wrong" critic step                      | 2     | 55% (28–79%)                   | 4/6         | 0/3              |

The critic step ran on the 3 calls with the most criticisms; Gemini's Flex tier was busy twice on one of them, so the
paired comparison has 2 calls. Neither change helps: the coach's criticisms are mostly single moments inside a skill he
otherwise praises, while the rubric rates the whole pattern ("one small miss can still be 4"). Whether Brain 4.0 catches
his criticisms is better measured on its coaching words, moment by moment, than on its 1–5 rating, and the fair test
needs his own blind ratings of the dimensions (section 6).

Shown in Admin → Gold set → Brain 4.0 evaluation as checkpoint "gold-v1/2026-10-21". From here on, new judgements
come from fresh `/review` assignments and pair with Brain 4.0 automatically.

## 9. Owner decision, 22 Oct 2026: Brain 4.0 live as the AI coaching score

The owner's words, relayed verbatim by the orchestrator (22 Oct, about 17:05–17:10 IST):

> "yes get that out a beta and the new brain live on production right now"
>
> "yes still we need the report structure given by dipak to be live only"

This is the owner's explicit override of the AC-SVAL gate for how Brain 4.0 is **displayed**:

- The coaching lead's 18-skill structure replaces the 27-pointer analysis on every call that has a Brain 4.0 read.
- The "Beta" label goes.
- The scores are named "AI coaching score": rated by AI, never "certified" or "official".
- Calls without a read fall back to the earlier analysis.

The gates themselves keep running in the background:

- the blind 18-skill reviews (checkpoint fresh-1, Gate 0 and Gate 3);
- the Admin evaluation with its drop alerts;
- this report.

None of them is a claim made to users.

**Numbers at the time of the decision** (section 8; gold v1, 6 calls, 43 labels, Wilson 95%):

| Pipeline                                          | Agreed with the coaching lead's notes |
| ------------------------------------------------- | ------------------------------------- |
| Today's classic pointer review (Gemini)           | 64% (49–77%)                          |
| Brain 4.0 product prompt on Gemini 3.8 Flash Flex | 55% (38–70%)                          |
| Brain 4.0 product prompt on GPT-6 Luna Flex       | 39% (28–50%)                          |

All the intervals overlap. Brain 4.0 on Gemini caught 1 of 8 of his criticisms. Brain 4.0 on Luna kept only 7 of 46 praise labels, and gave the same rating on a second read only 69% of the time.

**The owner's approval for every workspace** (his own words, in the data-change form, relayed by the orchestrator on 22–23 Oct 2026):

> "approve data change: Brain 4.0 AI coaching score for every workspace on production (including Wise Life and personal accounts), overriding the AC-SVAL gate"

Align 3 applied it on production with `scripts/data-changes/report-scoring.py --every-workspace`, which chooses the Brain 4.0 version for Report settings' general scope. This is the recorded override of the AC-SVAL display gate for every workspace. Gate 0, Gate 3 and the gold evaluation continue unchanged.

**Which engine to use:** Brain 4.0's production read stays on Gemini 3.8 Flash (`brain4_shadow`), the better of the two measured engines. It is a separate read from the one-pass C4 request, so switching C4 to Luna does not change which engine rates the 18 skills.
