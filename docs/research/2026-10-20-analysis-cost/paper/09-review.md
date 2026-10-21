# 9. Independent cross-review (Codex GPT-6.1 Sol; Gemini 3.8 Flash via agy), 21 Oct 2026

Both reviewers read the draft paper, the score tables, the request ledger and the harness code, without seeing each
other's review. Full texts: `results/reviews/review-codex.md`, `results/reviews/review-agy.md`.

**Verdicts.** Codex: *disagree* — "a promising research candidate, but does not establish ≤ ₹0.40 tomorrow without
losing quality or a validated ₹0.10 pipeline". Gemini: *agree with changes* — the cost diagnosis and the one-pass
consolidation are sound, the "tomorrow" pipeline cannot be approved as written.

## Where both agree (and what changed)

| Finding | Response in this version |
|---|---|
| The end-to-end candidate (Flash-Lite transcript) was compared with today's pipeline on a *perfect* transcript, and fails the unsupported-facts gate (+4.9 points [+2.7, +7.3]); Scribe was never measured | Stated as a failed gate. Added the fair same-input comparison (today's pipeline on the same Flash-Lite transcripts, 6.7): today rises from 0.3% to 4.0% unsupported on them too, and the one pass is level with it (+1.2 [−0.3, +2.9]), so the rise belongs to the transcriber. The Scribe control is now a precondition of any transcriber switch (7.3). |
| Flex was never called; its costs are half-price projections, and short calls still exceed ₹0.40 on standard | All Flex numbers are labelled projections; standard-tier measured numbers shown alongside; Flex latency/fallback measurement added to the shadow week. |
| AC-SVAL: the one pass writes fresh pointer scores; audio to Google is a new data flow | The recommended pipeline keeps today's pointer review unchanged; pointers inside the one pass only after an AC-SVAL review; audio needs the owner's approval. |
| Speaker attribution is not validated end to end; the speaker metric is rough | Listed as a limitation; role-attribution scoring is in the next round. |
| Two different "today" baselines (staging ₹1.19 vs fictional ₹1.03 at 13.8 min) | Explained (fictional calls produce fewer segment labels per minute); savings quoted against staging. |

## Where they differ

| Point | Codex | Gemini | Taken |
|---|---|---|---|
| Overall | not established | sound with changes | Both: the analysis-pass result is solid; the transcriber switch needs the Scribe control and the owner's data-flow decision. |
| Long-term model | gates first; Luna not validated end to end | **Gemini 3.8 Flash doubles in price on 1 Jan 2027**; Luna (stable $0.10/$0.50) beats 3.8 Flash on facts, unsupported facts and cost | Added 2027 prices: the Gemini-analysis pipeline becomes ₹0.25/min at 13.8 min and ₹0.56 at 4.5 min on Flex, so Luna is the durable ₹0.10 route (7.4). |
| What to try first | contract-preserving fixes: dedupe, timer no-ops, compact JSON, caching, silence trimming | VAD silence trimming (claims 20–35% silence), caching, key compression, short-call triage | Kept as "tomorrow" steps. Silence trimming is not worth much here: measured gaps over 1.5 s are 3–4% of real staging audio (17 Oct). |
| Statistics | paired call bootstrap required (computed −7.0 to +8.5 recall) | needle gate (≥ 90%) fails | Bootstrap added (6.6); needle gate failure stated — today's pipeline fails it too (75%). |
| Costs | ledger keeps last success only; retries and audio pricing mixed | fits paired ASR cost with oracle analysis | Fits now pair each transcript with the analysis run on that transcript; rerun exclusion stated. |

## Errors the reviewers found that were corrected

- The Luna end-to-end row was shown as "(judging)" although it had finished: recall 88.9%, critical 88.6%, unsupported
  2.8%, coaching truths 72% (equal to today). Now reported; it is the strongest pipeline in the study.
- Sarvam's critical-fact retention (55.9%) mixed a transcription failure (5 long calls returned HTTP 500 in the same
  second) with quality; those calls were re-run.
- Gemini 2.5 Flash-Lite cannot be the cheaper fallback: it answers 404 "no longer available to new users".
