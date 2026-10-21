# Accuracy Brain 4.0 in Sales X-Ray: mapping, scoring options and the AC-SVAL plan

21 Oct 2026. Requested by the orchestrator for the owner's ask: "is new brain 4.0 + Dipak's gold dataset
corrections live on PROD? I need all work we did to be on prod now."

Code (workbench): `packages/python/ac_platform/conversation_intelligence/brain4.py` (the review part),
`brain4_eval.py` (gold-set evaluation), `brain4_shadow.py` (shadow reads), Admin → Gold set → **Brain 4.0
evaluation** (`/gold/brain4`), API `GET /v1/admin/conversation/gold-evaluation`, Report settings
`report.scoring`, the Report's beta section (`xray-report/brain4*`). Commits c47d422d, 094d34a0, 02f916ce,
ec1c5466; the shadow read (migration 0117) waits for v0.74's release candidate.

## 1. What Brain 4.0 is, and what the product uses

- **Source:** `Accuracy Brain 4.0.txt`, 25,465 lines, SHA-256 `0d122e48…3ed0c` (the coaching lead's Drive
  document, read in full on 20 Oct by the cost research). 18 dimensions in 3 categories. It has **no weights
  and no aggregation rule**, and its own examples sometimes score the same moment in two dimensions at
  different severities (digest A §11.1).
- **What the prompt carries:** a compact digest of it, `profiles/brain4_compact_v1.txt` (67 lines, SHA-256
  `e8938fdf…7e41c`, revision `brain4-compact/1`). The research wrote it; the coaching lead has not signed it
  off. ADR 0036 D5 says rubric content ships only from what he signed off, so **the digest needs his review
  before any Brain 4.0 score can be official.** For the beta it is pinned by digest: changing one character
  fails closed until the revision is bumped.

## 2. The 18 dimensions on today's 27 pointers

"Primary" means the pointer asks the dimension's question; the gold-set comparison uses primary pointers
only. "Related" pointers overlap part of a dimension and are listed for the coaching lead's review.

| Dimension                                | Category              | Primary pointer(s)                            | Related                                     |
| ---------------------------------------- | --------------------- | --------------------------------------------- | ------------------------------------------- |
| D01 Starting the Call                    | How You Talk          | Call Opening & First Impression               |                                             |
| D02 Setting the Plan                     | How You Talk          | Purpose & Agenda Setting                      |                                             |
| D03 Tone, Pace & Pauses                  | How You Talk          | Tone and Energy; Handling Silence             | Overall Communication                       |
| D04 Listening Well                       | How You Talk          | Active Listening                              |                                             |
| D05 Asking the Right Questions           | How You Talk          | Open-Ended Questions; Asking Enough Questions |                                             |
| D06 Building Connection                  | How You Talk          | Building Rapport                              |                                             |
| D07 Being Professional (+ ethics gate)   | How You Talk          | Professionalism                               |                                             |
| D08 Finding the Decision-Makers          | Understand the Buyer  | Prospect's Role; Identifying Stakeholders     |                                             |
| D09 Understanding Problems & Goals       | Understand the Buyer  | Identifying Needs and Challenges              |                                             |
| D10 Understanding What They're Doing Now | Understand the Buyer  | Exploring Current Solution                    | Handling Competition                        |
| D11 Understanding the Real Impact        | Understand the Buyer  | Quantifying Business Impact                   | Creating Value                              |
| D12 Understanding How They Will Decide   | Understand the Buyer  | Understanding Decision Process                |                                             |
| D13 Matching the Right Solution          | Move the Sale Forward | Positioning Solution Value                    | Creating Value                              |
| D14 Explaining the Solution Clearly      | Move the Sale Forward | Presenting the Solution                       | Overall Communication                       |
| D15 Talking About Price & Budget         | Move the Sale Forward | Discussing Pricing                            |                                             |
| D16 Handling Objections                  | Move the Sale Forward | Handling Objections                           | Checking for Concerns; Handling Competition |
| D17 Asking for the Decision              | Move the Sale Forward | Closing Attitude                              |                                             |
| D18 Setting Clear Next Steps             | Move the Sale Forward | Next Steps                                    |                                             |

**No Brain 4.0 dimension:** Question to Talk Ratio (the rubric forbids scoring counts and talk ratio) and
Call Control. **Decision for the coaching lead:** keep both pointers outside Brain 4.0, or say which
dimension owns them.

## 3. Per-dimension output (contract `brain4-review/1`)

For each dimension: `applicability` (applicable, not applicable, not enough evidence), `rating` 1–5 or "–",
`confidence` (never changes the rating), up to 2 evidence segments (quotes copied from the saved transcript,
never from the model), `observed` (what happened), one `coaching` cue, and for D07 the ethics gate
(PASS / WARN / FAIL). Plus the call type.

The checker applies the rubric's own hard rules and records each change on the dimension:

| Rule (rubric wording)                                                              | What the checker does                                              | Recorded as            |
| ---------------------------------------------------------------------------------- | ------------------------------------------------------------------ | ---------------------- |
| "5 needs positive evidence"; "nothing went wrong is 4"                             | a 5 with no evidence becomes 4                                     | `five_needs_evidence`  |
| "Never turn missing evidence into a low score"; 1 only for clearly observed damage | a 1 with no evidence becomes "–"                                   | `one_needs_evidence`   |
| D03 needs audio; from a transcript only problems can show                          | a D03 rating above 3 becomes "–"; any D03 rating is low confidence | `delivery_needs_audio` |
| "One material violation = 1 and FAIL"                                              | FAIL and 1 always go together                                      | `ethics_fail_is_one`   |

## 4. Scoring and aggregation: options, not weights

The source has no weights. These are the choices for the coaching lead, through the owner. All are computed
when the report is read (`brain4.rollup`), so a later choice applies to every call already analysed.

| Option                              | Category number                                                   | Overall number                                             | Notes                                                  |
| ----------------------------------- | ----------------------------------------------------------------- | ---------------------------------------------------------- | ------------------------------------------------------ |
| **A. Category mean** (beta default) | mean of the category's rated dimensions, shown when ≥ 2 are rated | none                                                       | least invented; "–" never counts                       |
| B. Dimension mean                   | as A                                                              | mean of every rated dimension                              | categories with more dimensions weigh more (7 / 5 / 6) |
| C. Equal categories                 | as A                                                              | mean of the three category means, only when all three show | each category a third                                  |
| D. Profile only                     | none                                                              | none                                                       | 18 ratings, no roll-up at all (closest to the source)  |
| E. Coach weights                    | as A, weighted                                                    | weighted                                                   | needs the coaching lead's weights per dimension        |

In every option the **ethics gate is shown beside the numbers and never averaged** (the rubric: "FAIL is never
averaged away"). Whether a FAIL should also hide or cap the overall number is the coaching lead's call.

**Scale on the Report:** Brain 4.0 rates 1–5. The pointer review's 0–100 is not converted for display (no
invented mapping). For comparing with the gold set only, 5 = excellent, 4 = good, 3 = average, 1–2 = needs
improvement.

## 5. In the analysis

Two ways a call gets a Brain 4.0 read; the Report and the evaluation take either.

1. **Shadow read (built; migration 0117, for v0.75).** The pointer review job (`ac-pointer-review`, already
   running in every environment's worker) reads Brain 4.0 after its own pass: every report a gold reviewer is
   assigned, and the newest reports (48 h) of organisations whose Report settings show Brain 4.0 beta. One
   Gemini 3.8 Flash request per report on its saved transcript, the pointer review's own admission before the
   call and before saving, at most two attempts, saved in `conversation_brain4_reviews` (erased with the call's
   pointer reviews). Spend: AI spend guard feature **`brain4_shadow`, ₹0 in every environment until raised in
   Admin → AI spend** (that raise is the approval). Cost per read: about 5k instruction tokens plus the
   transcript in, about 2–3k out: roughly ₹2 a 14-minute call on standard, ₹1 on Flex.
2. **Inside the one-pass review request (proposed to the one-pass session, not built).** `PART brain4` with
   `brain4.part_instructions()` and schema `brain4.response_schema()`, checked by `brain4.parse`, saved inside
   the pointer review payload under `brain4`. Marginal cost about ₹0.03 per audio minute on Gemini Flex. When a
   review carries its own block, the shadow read skips that call (except gold calls, where a second read
   measures repeatability).

Per organisation: Report settings → "Scoring rubric: Classic / Brain 4.0 beta" (a display setting). With
Brain 4.0 beta, the Report's Part 2 shows the 18 skills (Beta) above the 27 pointers; with classic, nothing
changes.

## 6. AC-SVAL: what the gold set can and cannot show

The gold set is the coaching lead's phone review (`/review`, since v0.62): for each of the 27 pointers of a
call's AI pointer review he agrees, partly agrees or disagrees, and may give the right score or status and why.

What `brain4_eval` measures, per dimension, on the same gold lines for Brain 4.0 and for today's review:
exact band, within one band, quadratic weighted kappa, mean band error and lean, whether both call the pointer
judgeable, and whether Brain 4.0 moved the right way where he said only "too harsh" or "too generous".
Intervals resample whole calls (lines of one call are not independent).

Limits (AC-SVAL-01 §§ 8, 12):

1. **One rater.** Gate 0 needs two independent expert raters and their agreement first; there is none yet.
2. **Not blind.** He judged today's AI answer while seeing it, so an "agree" makes today's band the gold band.
   Today's review is favoured in every comparison.
3. **Pointers, not dimensions.** Brain 4.0 is compared through the pointers that ask its question.

So the set can show where Brain 4.0 is a reasonable beta, and where it disagrees with him. **It cannot make
any dimension official.** Each dimension's state in Admin is "needs data", "beta" or "Gate 3 candidate"
(n ≥ 50 calls, weighted kappa ≥ 0.70 with its interval, within one band ≥ 90%); never "official".

**What official needs (per dimension):** the coaching lead's sign-off of the digest and the mapping; a second
blinded rater on a frozen set (Gate 0, kappa ≥ 0.70); the coaching lead rating Brain 4.0's dimensions blind on
≥ 50 calls with ≥ 10 rated per dimension (Gate 3); and Gate 4's human-confirmed decisions before any score is
official.

## 7. Calibration

- Display only and versioned (`brain4.Calibration`); revision 0 changes nothing. `brain4_eval.fit_calibration`
  fits, per dimension, the band the gold set most often endorses for each Brain 4.0 rating (order kept, at least
  8 lines per rating). A fit is committed as a new revision with its gold-set dates and counts.
- The one-pass session's `one-pass-pointer-calibration/1` (16-call trial) calibrates one pass's pointer scores
  to today's review. The gold set can replace that fit with offsets to the coaching lead's own scores where he
  gave them, once there are enough per pointer.

## 8. Closing the loop

- New gold answers count on the Admin page as soon as they are saved (no job, no copy).
- Every call assigned to a gold reviewer gets a Brain 4.0 shadow read (once its spend cap is raised), so his
  answers on it pair up with Brain 4.0 automatically; so do Brain 4.0 blocks saved with pointer reviews.
- Alerts: when the newest 60 answers' acceptance (today's review) or within-one agreement (Brain 4.0, per
  dimension) falls 10 points below the earlier rate and the fall is outside the window's 95% interval, Admin shows
  it on the page.

## 9. Measured on the fictional set, and the AC-SVAL report

`AC-SVAL-REPORT.md` (interim: production gold reads await the owner's approval). On 16 fictional calls × 3
reads (GPT-6 Luna Flex, bench key): 48/48 answers passed the contract; the same rating in three reads on 56% of
calls on average, within one point on 95%; D07's ethics gate is the least stable (75% within one point).
