# 6. Results (round 1: 16 fictional calls, 264 audio minutes; real-speech set 31 minutes)

All quality numbers are from two LLM judges of different families (Claude Haiku 5.5 primary on every arm; Gemini 3.8
Flash second on the arms the recommendation rests on). They agree within 1–5 points; the larger gap is on today's
pipeline (70.6% vs 75.6% recall). Costs are measured receipts: OpenRouter's billed amount (Gemini pinned to AI Studio
prices), list price per audio minute for transcribers. ₹ at ₹100/$. Files: `results/scores/*.md|json`.

## 6.1 Transcription

**Real human speech (Google FLEURS, 70 sentences per language; transliterated CER, lower is better):**

| Transcriber | Hindi clean | Marathi clean | Hindi phone | Marathi phone | ₹/min |
|---|---:|---:|---:|---:|---:|
| Gemini 3.1 Flash-Lite (audio in) | **2.5%** | **4.2%** | 10.9% | 26.0% | 0.143 (Flex 0.072) |
| Sarvam saaras:v4 + diarization | 3.1% | 4.7% | **9.2%** | **25.6%** | 0.59 |
| AssemblyAI Universal-2 | 5.2% | 39.0% | 30.5% | 57.4% | 0.28 |
| Deepgram Nova-3 multilingual | 15.6% | 32.9% | 39.4% | 96.3% | 0.52 |
| Groq Whisper large-v3-turbo | 17.6% | 45.1% | 40.6% | 57.3% | 0.067 |
| Groq Whisper large-v3 | 36.8% | 45.6% | 32.7% | 59.9% | 0.185 |
| Gemini 3.8 Flash | — | — | — | — | stopped mid-answer on these Wikipedia sentences (recitation filter); fine on calls |

**Fictional phone calls (16 calls; tCER; speaker accuracy by time overlap; critical-fact retention judged):**

| Transcriber | tCER | Speaker acc. | Critical facts retained | Garbled | Marathi–English retained | ₹/min |
|---|---:|---:|---:|---:|---:|---:|
| **Gemini 3.8 Flash** | **7.5%** | **100%** | **96.0%** | 3.8% | 93.8% | 0.228 (Flex 0.114) |
| **Gemini 3.1 Flash-Lite** | 18.1% | 76.6% | **93.3%** | 6.5% | 89.6% | 0.143 (Flex 0.072) |
| Sarvam saaras:v4 (11 of 16 calls; free credit ran out) | 12.6% | 92.6% | 89.0% | 11.0% | 86.1% | 0.59 |
| Gemini 3.5 Flash-Lite | 29.5% | 73.5% | 82.8% | 10.3% | 67.5% | 0.142 |
| Groq Whisper large-v3 / turbo | 25.6% / 28.2% | ~51% (no diarization) | 81.2% / 80.2% | ~15% | 71% / 65% | 0.185 / 0.067 |
| AssemblyAI U3.5 Pro / U2 | 21.9% / 25.3% | 96–97% | 80.4% / 75.7% | 16–20% | 66% / 49% | 0.383 / 0.283 |
| Deepgram Nova-3 | 24.4% | 80.3% | 76.6% | 19.3% | 50.6% | 0.52 |
| faster-whisper turbo, self-hosted (4 vCPU) | scored in round 2 | no diarization | | | | real-time factor 0.51 |

Scribe v2 (today's transcriber) is not in these tables: no ElevenLabs bench key was available, and the shared
production key was not used without approval.

## 6.2 Analysis quality on the true transcript (isolates the text model)

| Arm | Fact recall | Critical | Needles | Traps | Halluc. | Facts/call | Coaching truths covered | False claims/call | ₹/min |
|---|---:|---:|---:|---:|---:|---:|---:|---:|---:|
| **Today: 6 passes on 3.8 Flash** | 70.6% (76% G) | 74.6% | 75.0% | 85.7% | 0.3% | 79 | 72.0% | 1.12 | 0.584 |
| One pass, 3.8 Flash, exhaustive prompt (v2) | 80.7% (81% G) | 84.7% | 70.8% | 89.3% | 0.2% | 35 | **78.8%** | **1.00** | 0.155 |
| One pass, 3.8 Flash, first prompt (v1) | 64.8% | 71.2% | 66.7% | 72.6% | 0.6% | 22 | 74.6% | 0.88 | 0.141 |
| **One pass, GPT-6 Luna** | **93.7%** (94% G) | **94.6%** | **91.7%** | **94.0%** | 0.3% | 59 | 67.8% | 1.31 | **0.030** |
| One pass, Claude Haiku 5.5 | 83.7% (86% G) | 88.2% | 79.2% | 89.3% | 0.3% | 40 | 58.5% | 1.50 | 0.033 |
| One pass, Gemini 3.5 Flash-Lite | 43.4% | 50.3% | 12.5% | 70.2% | 0.0% | 18 | 55.9% | 1.38 | 0.075 |
| One pass, Gemini 3.1 Flash-Lite (v2) | 50.3% | 57.0% | 25.0% | 69.0% | 1.6% | 23 | 43.2% | 1.88 | 0.043 |
| One pass, DeepSeek / GLM / MiMo / gpt-oss / Qwen | see `facts.md` | | | | | | | | 0.010–0.050 |

(G = second judge, Gemini 3.8 Flash.) **A single pass matches or beats today's six-pass pipeline on facts and on
coaching**, at a quarter of the LLM cost on the same model. The prompt matters: the exhaustive-facts prompt added 16
points of recall on 3.8 Flash. GPT-6 Luna extracts the most facts; Gemini 3.8 Flash writes the best coaching.
Flash-Lite models are not good enough to write the analysis.

## 6.3 End to end (audio → transcript → analysis), judged against the true facts

| Transcriber → analysis | Recall | Critical | Needles | Traps | Halluc. | Truths covered | ₹/min @13.8 (std / Flex) |
|---|---:|---:|---:|---:|---:|---:|---:|
| Gemini 3.1 FL → 3.8 Flash one pass v2 | 71% (73% G) | 77% (79% G) | 71% | 85% | 5% (3% G) | 79% | 0.32 / **0.16** |
| Deepgram → 3.8 Flash one pass v2 | 66% | 70% | 46% | 75% | 10% | 70% | — |
| Gemini 3.1 FL → 3.8 Flash one pass v1 | 56% | 64% | 50% | 70% | 6% | 75% | 0.28 / 0.14 |
| **Gemini 3.1 FL → GPT-6 Luna** | **88.9%** | **88.6%** | **87.5%** | **90.5%** | 2.8% | 72% | 0.107 / **0.089** |
| Audio → 3.1 Flash-Lite in one call (shape c) | 23% | 27% | 8% | 42% | 9% | 36% | 0.255 |
| *Reference: today's pipeline on the **true** transcript* | *71% (76% G)* | *75% (79% G)* | *75%* | *86%* | *0.3%* | *72%* | *1.03 with Scribe* |

The candidate Google-only pipeline, starting from real (imperfect) Flash-Lite transcripts, scores the same as today's
pipeline does on a *perfect* transcript, and covers more coaching truths. Its hallucination rate rises to 3–5% because
misheard words become wrong facts. Today's pipeline pays the same price on the same transcripts (4.0% unsupported, 6.7);
through Scribe's errors it would pay a price this round could not measure. Shape (c) — Flash-Lite hearing the audio and writing everything in one answer — fails.

## 6.4 Measured cost per audio minute (fixed per call + per minute, from the ledger)

| Pipeline | 4.5 min | 13.8 min | 60 min |
|---|---:|---:|---:|
| Today: Scribe + 6 stages on 3.8 Flash | ₹1.98 | ₹1.03 | ₹0.67 |
| Scribe + one pass 3.8 Flash (v2) | ₹0.84 | ₹0.55 | ₹0.43 |
| Gemini 3.1 FL transcript + one pass 3.8 Flash, standard | ₹0.63 | ₹0.32 | ₹0.21 |
| **Same, Flex tier** | **₹0.32** | **₹0.16** | **₹0.10** |
| Gemini 3.8 Flash transcript + one pass 3.8 Flash, Flex | ₹0.36 | ₹0.20 | ₹0.15 |
| **Gemini 3.1 FL (Flex) + GPT-6 Luna one pass (Flex)** | **₹0.12** | **₹0.089** | **₹0.078** |
| Gemini 3.1 FL (Flex) + Haiku 5.5 one pass | ₹0.18 | ₹0.11 | ₹0.08 |

The one pass on 3.8 Flash has a fixed ≈ ₹2.0 per call (≈ 4k-token compact JSON output), so short calls cost more per
minute; Flex is what keeps a 4.5-minute call under ₹0.40.

## 6.5 Shape (d): distilling the deep pipeline's segment labels

1,253 fictional segments labelled by today's Gemini labeller; multilingual sentence embeddings (e5-small, LaBSE) +
logistic regression, leave-one-call-out:

| Label | Classes | Agreement with the LLM | Majority-class baseline |
|---|---:|---:|---:|
| act | 8 | 35–42% | 52% |
| sentiment | 3 | 56–61% | 55% |
| intent | 16 | 33% | 21% |
| tone | 8 | 33–39% | 24% |

A small classifier cannot reproduce the LLM's per-segment labels from ~1,000 examples (and those labels are themselves
noisy: 3.8 Flash flips ~30% of pointer verdicts between runs). The hybrid's value is elsewhere: the measured audio
features stay local, and the per-segment labels are dropped or folded into the one pass.

## 6.6 Uncertainty (paired bootstrap, 16 calls, 20,000 resamples, Haiku judge)

| Arm − today's pipeline on the true transcript | Recall | Critical | Needles | Traps | Unsupported | Coaching |
|---|---|---|---|---|---|---|
| Flash-Lite transcript → 3.8 Flash one pass (v2) | +0.4 [−7.1, +8.4] | +2.2 [−5.5, +9.9] | −4.2 [−30, +20] | −1.2 [−11, +7] | **+4.9 [+2.7, +7.3]** | **+6.8 [+0.8, +13.9]** |
| 3.8 Flash one pass (v2), true transcript | **+10.1 [+3.9, +16.7]** | **+10.1 [+4.5, +16.0]** | −4.2 [−28, +17] | +3.6 [−3.7, +11.1] | −0.1 [−0.6, +0.2] | **+6.8 [+1.0, +12.3]** |
| GPT-6 Luna, true transcript | **+23.0 [+18.1, +27.6]** | **+20.0 [+14.6, +24.4]** | +16.7 [−4, +38] | **+8.3 [0, +17]** | 0 [−0.5, +0.5] | −4.2 [−11.9, +2.2] |
| Flash-Lite transcript → GPT-6 Luna | **+18.2 [+14.7, +21.7]** | **+14.0 [+10.4, +17.2]** | +12.5 [−6, +28] | +4.8 [−3, +12.5] | **+2.5 [+1.3, +3.9]** | 0 [−9.2, +8.3] |
| Claude Haiku 5.5, true transcript | **+13.1 [+3.3, +21.9]** | **+13.6 [+5.3, +20.8]** | +4.2 [−22, +27] | +3.6 [−6, +13] | 0 [−0.6, +0.6] | **−13.6 [−20.7, −5.8]** |

Bold: the interval excludes zero. Facts within a call are not independent, which is why calls are resampled.

## 6.7 Same input: today's pipeline on the same Flash-Lite transcripts (the fair shape comparison)

Section 6.6 compares end-to-end arms with today's pipeline on a *perfect* transcript, which charges the new arms for
transcription errors that today's pipeline never saw. Here today's six stages also read the Gemini 3.1 Flash-Lite
transcripts, so both sides carry the same errors and only the pipeline shape and model differ.

| On the same Flash-Lite transcripts | Recall | Critical | Needles | Traps | Unsupported | Coaching |
|---|---:|---:|---:|---:|---:|---:|
| *Today's 6 stages, 3.8 Flash* | *68.4%* | *72.7%* | *58.3%* | *84.5%* | *4.0%* | *77.1%* |
| One pass 3.8 Flash (v2) | 71.1% | 76.8% | 70.8% | 84.5% | 5.2% | 78.8% |
| One pass GPT-6 Luna (v1) | 88.9% | 88.6% | 87.5% | 90.5% | 2.8% | 72.0% |
| One pass Claude Haiku 5.5 (v2) | 89.8% | 89.0% | 91.7% | 92.9% | 3.5% | 53.4% |

| Arm − today, same input (95% interval) | Recall | Critical | Needles | Traps | Unsupported | Coaching |
|---|---|---|---|---|---|---|
| One pass 3.8 Flash (v2) | +2.7 [−4.5, +10.3] | +4.1 [−3.5, +11.9] | +12.5 [−17, +38] | 0 [−8.2, +8.2] | +1.2 [−0.3, +2.9] | +1.7 [−6.4, +10.9] |
| One pass GPT-6 Luna (v1) | **+20.5 [+16.5, +24.3]** | **+15.9 [+12.2, +19.2]** | **+29.2 [+11, +49]** | **+5.9 [+1.2, +11.5]** | −1.2 [−2.6, +0.1] | −5.1 [−16.4, +5.6] |
| One pass Claude Haiku 5.5 (v2) | **+21.4 [+15.7, +26.9]** | **+16.3 [+11.3, +21.2]** | **+33.3 [+7, +60]** | **+8.3 [0, +16.7]** | −0.5 [−1.6, +0.7] | **−23.7 [−32.1, −15.8]** |

What this settles:
- **The unsupported-fact rise in 6.6 comes from the transcript, not from the one pass.** Today's own pipeline goes from
  0.3% unsupported facts on the perfect script to 4.0% on the Flash-Lite transcripts. On the same input, the 3.8 Flash
  one pass is level with today on every metric (all intervals include zero) at about a quarter of the analysis cost.
- **GPT-6 Luna is better than today on facts and no worse on unsupported facts** on the same input; coaching is
  inconclusive (−5 [−16, +6]). Haiku finds as many facts but loses a quarter of the coaching truths.
- **Still open:** whether Flash-Lite transcripts carry more errors into facts than Scribe's do. That is the Scribe control
  (7.3); this round could not run Scribe.

## 6.8 Known weaknesses of this round (from the independent reviews)

- **Two "today" baselines.** The staging fit (₹1.19 at 13.8 min) is the production truth; the replica on fictional calls
  costs ₹1.03 because those calls produce fewer segment labels per minute. Savings are quoted against the staging fit.
- **Flex was not called**; its prices are projections. Very short calls stay expensive (the 2.5-minute fx-07 costs
  ₹0.50/min even on projected Flex).
- **The new arms are scored on facts in the benchmark's own type vocabulary**, while today's facts are spread across
  fast, deep and C4 outputs (C5 and pointer text are not mined for facts); judge inputs drop speaker roles and anchors,
  so this is not an exact-match or attribution test. Judges of one family judge their own family's output on some rows.
- **Speaker accuracy** is a rough time-overlap mapping, not DER/cpWER; role recovery by the analysis pass is not scored.
- **Cohorts differ slightly** (Gemini 3.8 Flash transcription failed on 2 calls, so its retention covers 477 critical
  facts rather than 535).
- **Costs keep the last successful request per call and stage**: research reruns are excluded, but so would be billable
  production retries; HTTP-level retries are not logged.
