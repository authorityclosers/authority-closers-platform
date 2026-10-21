# 10. Real calls scored against the coaching lead's notes, and the Brain 4.0 prompt (rounds 3–7, 21 Oct 2026)

## 10.1 Data and approvals

- **Calls:** seven real sales calls (8.8–23.9 min, 108 audio minutes; Hindi, Marathi, English), linked from the
  coaching lead's document "1. Language simplicity". Six carry his timestamped notes: 81 notes in all (strengths,
  improvements, observations of the buyer). The notes are the gold standard; they were written as the lead listened.
- **Approval:** the owner approved processing these seven calls for research on 21 Oct (first with zero-retention
  routing: Gemini on Google Vertex, GPT-6 Luna on Azure; then "retention and training do not matter for these
  calls"). Audio, transcripts, notes and names stay on ac (`realcalls/`, mode 700); only ids `rc-01…07` and aggregate
  scores are in this folder.
- **Rubric:** "Accuracy Brain 4.0" (25,466 lines, 18 dimensions in 3 categories) was read in full by two agents;
  their digests are in `brain4/`. `harness/brain4_rubric.txt` is the compact prompt (≈ 2,700 words) written from the
  digests; lines that echoed the coaching lead's notes on these seven calls were removed before any run, so the
  prompt does not leak the gold notes.

## 10.2 Method

Every pipeline read the same Gemini 3.1 Flash-Lite transcript of each call. Judges (Claude Haiku 5.5 and GPT-6 Luna
on every pipeline; Gemini 3.8 Flash on most; Claude Sonnet through the Claude subscription, no API spend, on the main
ones) marked each note covered (1), partly covered (0.5) or not covered, and listed false claims. Coverage is pooled
over notes; the paired bootstrap resamples calls (20,000 draws).

Rounds: 3 = today's six stages, Gemini one pass, Luna one pass (two prompts); 4 = the Brain 4.0 one pass on GPT-6
Luna, Luna Pro, Gemini 3.8 Flash, Claude Sonnet 5.5, GPT-6.1 Sol; 5 = plus delivery observations heard by Gemini
Flash-Lite; 6 = plus pause statistics measured with ffmpeg; 7 = plus 10–20 timestamped coach notes.

## 10.3 Results (Haiku + Luna judges; analysis ₹/min measured on these calls; transcription adds ₹0.24)

| Pipeline | Notes covered | vs today (95% interval) | ₹/min analysis |
|---|---:|---|---:|
| Brain 4.0 + measured pauses + coach notes, Gemini 3.8 Flash | **50.0%** | +4.0 [−1.8, +10.5] | 0.255 |
| One pass, Gemini 3.8 Flash (exhaustive prompt) | 45.7% | −0.3 [−7.1, +8.1] | 0.178 |
| *Today: Scribe + six Gemini 3.8 Flash stages* | *46.0%* | | *1.132* |
| Brain 4.0, Gemini 3.8 Flash | 43.2% | −2.8 [−12.0, +9.6] | 0.218 |
| Brain 4.0, Claude Sonnet 5.5 | 41.1% | −4.9 [−11.0, +2.1] | 1.544 |
| **Brain 4.0 + measured pauses + coach notes, GPT-6 Luna (Lean)** | **40.7%** | −5.2 [−10.8, +1.1] | **0.049** |
| One pass, GPT-6 Luna (first prompt) | 39.8% | −6.2 [−10.9, 0.0] | 0.030 |
| Brain 4.0, GPT-6.1 Sol | 39.2% | −6.8 [−14.2, +1.0] | 0.846 |
| Brain 4.0, GPT-6 Luna | 37.0% | −8.9 [−15.9, 0.0] | 0.045 |
| Brain 4.0 + measured pauses, GPT-6 Luna | 36.7% | −9.3 [−21.1, +2.9] | 0.044 |
| One pass, GPT-6 Luna (coaching walk-through prompt) | 36.4% | −9.6 [−13.7, −5.1] | 0.032 |
| Brain 4.0, GPT-6 Luna Pro | 35.5% | −10.5 [−16.1, −3.2] | 0.104 |
| Brain 4.0 + delivery heard by Flash-Lite, GPT-6 Luna | 33.7% | −12.3 [−18.5, −5.5] | 0.041 |

The third judge, Claude Sonnet on the subscription (no API spend), ranks the main pipelines the same way: Gemini
Brain 4.0 + coach notes 50.0%, Gemini one pass 45.1%, Sonnet Brain 4.0 41.4%, today 39.5%, Brain 4.0 + measured
pauses (Luna) 38.3%, Lean 37.0%, Luna one pass and Luna Brain 4.0 35.2%.

Fictional check of the Brain 4.0 prompt (Luna on Flash-Lite transcripts, Haiku judge): fact recall 90.5%, critical
89%, needles 88%, traps 92%, unsupported 3%, coaching truths 74% — at least as good as Luna's first prompt (88.9%,
88.6%, 87.5%, 90.5%, 2.8%, 72%). The rubric does not cost facts.

## 10.4 What this shows

1. **One pass loses nothing on real calls either.** Gemini's one pass equals today (−0.3) at a sixth of the analysis
   cost; with the Brain 4.0 rubric, measured pauses and coach notes it is the only pipeline ahead of today (+4.0, not
   yet significant with six calls).
2. **Luna is about 5 points behind on coaching**, at a fifth of Gemini's price and with the best facts. The coaching
   lead's notes are moment-level ("10:56 asked a question after describing — great"); the rubric alone made models
   stingy with strengths. Asking for 10–20 timestamped coach notes lifted Luna by about 4 points.
3. **Delivery must be measured, not heard by a model.** Measured silence share: 6.8% on the call the lead faulted for
   having no pauses, 22% on the call he praised for its pauses. Flash-Lite, listening to the same audio, said the
   salesperson "uses pauses effectively"; feeding its impressions lowered Luna's coverage (33.7% vs 37.0%).
   Measured pauses are free and accurate; on their own they did not move coverage, so their value is correct evidence
   for Tone, Pace & Pauses (D03), which the rubric says needs audio.
4. **Premium models are not the lever.** Sonnet 5.5 and GPT-6.1 Sol on the same prompt covered no more than Gemini 3.8
   Flash at 4–7× its price.
5. **Judges disagree by up to 20 points** and prefer their own family (the Gemini judge rates today's pipeline 59%,
   Haiku 38%), so every number above is a mean of two families.
6. **Transcription is now the largest cost**: ₹0.24 a minute on these dense calls (about 196 words a minute) against
   ₹0.14 on the fictional ones.

## 10.5 Limits

Six annotated calls and 81 notes: only differences of about 6 points or more are clear of noise. One annotator.
The notes are partial (some calls are annotated only for their first minutes). The "8–14 pauses a minute" reference
in the measured-pause prompt was calibrated on these seven calls; production should take it from the platform's own
calls. Scribe was not measured. Brain 4.0 scores are research output, not official scoring (AC-SVAL).

## 10.6 Jev and the subscriptions

- TypeSafe's Jev (a calibrated, non-generative decision model) is only reachable on OpenRouter as "Jev Router", which
  picks a model per request; the decision model itself is waitlisted. Once available it fits the 18 Brain 4.0 scores
  and yes/no checks, with the LLM keeping facts, evidence and coach notes.
- Judging does not need API credit: the Claude Code CLI on ac (Sonnet, subscription) judged the main rows
  (`harness/subjudge.py`).
