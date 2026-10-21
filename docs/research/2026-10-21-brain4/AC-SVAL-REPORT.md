# AC-SVAL report: Accuracy Brain 4.0 against the coaching lead's gold set (interim, 21 Oct 2026)

**Status: interim.** The gold set lives only on production. Reading it (labels only) and running Brain 4.0 on
those calls both wait for the owner's approval, so this report has no production agreement figures yet. What
it does have: the method, what the gold set can and cannot decide, Brain 4.0's behaviour on the 16 fictional
calls, and the exact steps that fill in the numbers once approved. Gates are from AC-SVAL-01 §12; its
thresholds are "engineering starting points", reported with intervals and counts.

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

## 7. Filling in the production numbers (once approved)

- **Route A (in place, preferred):** release v0.75 (migration 0117); the owner raises AI spend →
  `brain4_shadow` above ₹0 on production; the pointer review job reads Brain 4.0 on every gold call (one per idle
  pass); Admin → Gold set → Brain 4.0 evaluation shows the figures. Nothing leaves production. At about ₹2 per
  14-minute call (standard), 50 gold calls cost about ₹100.
- **Route B (labels-only read now):** a read-only query on `conversation_gold_rows` (verdict, score, status,
  reasons, skip, the AI's status and score; never the note) gives today's review's acceptance per pointer
  immediately, without Brain 4.0.
