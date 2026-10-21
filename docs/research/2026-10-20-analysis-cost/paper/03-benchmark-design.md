# 3. Benchmark design: what "good" means for our job

The job is not "summarise a call". It is: from a 2–60 min Indian phone sales call (English, Hindi, Marathi and
code-mix; often 8 kHz and noisy), produce (1) a transcript with speakers and times, (2) exact facts a salesperson
acts on (names, money in lakh/crore, dates, quantities, commitments, objections, next step), (3) pointer verdicts
and (4) a coaching report in the current Report structure, all valid JSON, with nothing invented. A cheaper
pipeline is acceptable only if it is **not worse than today's on the metrics that hurt a user**.

## 3.1 Metrics (each scored automatically against ground truth)

| # | Metric | Definition | Why it matters | Gate vs today (proposed) |
|---|---|---|---|---|
| M1 | **Fact recall** | share of ground-truth facts (type, slot, value) the output states correctly | missed budget / date = lost deal | ≥ today − 3 pts |
| M2 | **Fact precision** | share of stated facts that match ground truth | wrong facts mislead | ≥ today − 2 pts |
| M3 | **Critical exact-match** | names, phone-free identifiers, ₹ amounts (incl. lakh/crore), dates, quantities: exact after normalisation | the owner's "exact names, numbers, dates" | ≥ today |
| M4 | **Hallucination rate** | stated facts / quotes unsupported by the reference transcript (checked by an evidence anchor + string/number match, LLM judge only for paraphrase, two judges of different families) | invented facts destroy trust | ≤ today |
| M5 | **Speaker attribution** | who said it (salesperson / prospect / third party) for commitments, objections, prices | coaching is about the salesperson | ≥ today − 3 pts |
| M6 | **Needle recall by depth** | planted one-mention facts at 10 / 50 / 90% depth of 20–45 min calls, incl. non-literal ones (NoLiMa-style: question and needle share no keywords) | long calls lose the middle | ≥ 90% at every depth |
| M7 | **Code-mix robustness** | M1–M5 split by Hinglish / Marathi-English / English; ASR tWER and CER | most calls are code-mixed | no subset > 5 pts below today |
| M8 | **ASR quality** | transliteration-normalised WER (tWER: both sides mapped to one Roman scheme, numbers normalised), CER, **critical-token error rate** (names/numbers/dates in transcript), cpWER / WDER for speakers | a fact lost in ASR is lost for good | critical-token error ≤ today |
| M9 | **Valid structured output** | first-try parse + schema validation rate; repair-call rate | a repair is a second paid call and a delay | ≥ 99% after one repair |
| M10 | **Run-to-run consistency** | 3 runs per call: fact-set Jaccard; pointer-verdict agreement (Cohen's κ) | today's 3.8 Flash flips ~30% of pointer verdicts (17 Oct replay) | ≥ today |
| M11 | **Report quality** | rubric vs the ideal report (coverage of key moments, correct coaching points, actionable next step, no invented events), judged by two judges of different families blind to arm, plus a human spot check | the report is the product | ≥ today − 5% |
| M12 | **Latency** | p50 / p95 seconds to a finished report | users wait | p95 ≤ 2× today |
| M13 | **₹ / audio minute** | from actual receipts (tokens, audio seconds) × list price, at 4.5 / 13.8 / 60 min and on the real length mix | the objective | ≤ ₹0.40, then ≤ ₹0.10 |

Decision rule: among arms passing every gate M1–M12, pick the cheapest by M13; report the Pareto frontier
(cost vs a weighted quality score) so the owner can trade a little quality for cost knowingly. All differences are
reported with 95% bootstrap confidence intervals over calls (n ≈ 40 synthetic + public speech sets); a gate "passes"
only if the lower CI bound clears it.

## 3.2 Existing benchmarks and which apply

| Benchmark | What it measures | Use here |
|---|---|---|
| Needle-in-a-haystack (Kamradt), RULER (NVIDIA 2024), **NoLiMa** (ICML 2025: needles with minimal lexical overlap; 10 of 12 models fall below 50% of their short-context score at 32K) | long-context retrieval | **Design pattern for M6.** Our calls are 4–25k tokens, inside the range where NoLiMa shows real drops, so plant non-literal needles. |
| LongBench v2, HELMET, Fiction.LiveBench, MRCR | long-document understanding / coreference | Evidence only (cited per model in the market table); not run. |
| **JSONSchemaBench** (2025, 10K real schemas; tests constrained decoding incl. OpenAI and Gemini) | structured output | Method for M9; our own schema is the test. |
| IFEval, BFCL | instruction / function following | Evidence only. |
| Vectara HHEM leaderboard, FaithBench, FActScore, SummaC | summary faithfulness / hallucination | Method for M4 (claim decomposition + support check). |
| QMSum, MeetingBank, AMI, ICSI | meeting summarisation | Not sales, English; method only. No public sales-call benchmark exists; hence our own set. |
| **FLEURS (hi, mr), Kathbath (incl. noisy), IndicVoices, Lahaja (Hindi accents), Svarah (Indian English), MUCS 2021 (Hindi–English code-switch), Vistaar (59 Indic ASR sets)** | ASR WER on real Indian speech, CC-BY | **Use for M8 on real human speech**: small stratified samples (≈ 60 min) from IndicVoices hi/mr, Kathbath-noisy, Svarah, MUCS. Public consented datasets, so they may go to any provider. |
| **DISPLACE 2023/2024** (code-mixed Indian conversations, speaker + language diarization), DISPLACE-M 2026 (Hindi health-worker calls: diarization, ASR, summarisation) | diarization in code-mixed Indian speech | Use for speaker metrics if the licence allows research use; else our synthetic multi-party calls. |
| Open ASR Leaderboard (now with Monsoon en-IN / hi-IN sets) | ASR leaderboard | Evidence for the market table. |

**Why our own synthetic set is still needed:** no public set has Indian *sales* calls with fact sheets and
reports. TTS audio is cleaner and more regular than real calls, so synthetic WER is a *ranking*, not an absolute;
we degrade it to phone quality (8 kHz, μ-law/AMR-NB, noise, crosstalk, clipping) and cross-check ASR on the
real-speech public sets above. Real customer audio stays with the providers we already use (AGENTS.md gates).

## 3.3 Dataset (phase 2)

~40 fictional calls; every call has `script.json` (turns with speaker, language, text), `facts.json` (ground-truth
facts with type, value, turn id, and whether it is a planted needle), `ideal_report.json` (current Report
structure), and audio (clean + phone-degraded). Coverage matrix:

| Axis | Values |
|---|---|
| Call type | cold call, inbound lead follow-up, demo, objection-heavy, negotiation + close, lost deal, callback, multi-party (3–4 speakers) |
| Language | English (Indian), Hinglish, Marathi–English, Hindi-dominant, one Gujarati–English control |
| Length | 2–5 min (8), 6–15 (14), 16–30 (12), 31–45 (6) ≈ 11 h of audio |
| Audio | clean 16 kHz; phone 8 kHz μ-law/AMR-NB + noise (SNR 5–20 dB); one stereo (party per channel) |
| Needles | 2–4 per call ≥ 15 min, at 10/50/90% depth, half non-literal |
| Traps | numbers said two ways ("das lakh" / "10 L"), self-corrections ("Tuesday — no, Wednesday"), a third person's name, a competitor price, an off-topic personal detail |

Scripts are written by three different model families (Codex Sol, Claude, Gemini via agy) so no tested model grades
its own family's writing; the generator is a covariate. A checker verifies every fact value appears in the script
turn it cites, rejects real-looking phone numbers / emails / URLs, and uses fictional names and companies only.

## 3.4 Arms (phase 3)

Transcription: Scribe v2 (baseline, existing provider, fictional audio only), Gemini audio-in (3.8 Flash, 3.1/2.5
Flash-Lite; free-tier bench project), Groq Whisper large-v3 / turbo, Deepgram Nova-3 multilingual, AssemblyAI
Universal-2 / 3.5 Pro, Sarvam (Saarika/Saaras), self-hosted faster-whisper turbo on GitHub runners.
Text models: Gemini 3.8 Flash (baseline), 3.1/2.5 Flash-Lite, Haiku 5.5, GPT-6 Luna, DeepSeek V4.1 Flash, GLM-5.3 Flash,
Qwen 3.8 Flash, MiMo V2.6 Flash, gpt-oss-120b (Groq/Cerebras free).
Shapes: (a) today's multi-pass with today's prompts, (b) one pass / two cached passes, (c) audio in, (d) hybrid.
Not a full factorial: transcription arms are scored on M8 first; the best 3 transcripts feed the text arms; shapes
are crossed with the best 4 text models. Budget guard in the harness: hard stop at $20 OpenRouter + free tiers,
every request logged with tokens and list-price cost.
