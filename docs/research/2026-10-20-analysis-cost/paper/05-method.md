# 5. Method: dataset, audio and harness

## 5.1 Fictional call set (round 1: 16 calls, ≈ 4.6 h)

| id | type | language | min | writer | facts | needles | traps |
|---|---|---|---:|---|---:|---:|---:|
| fx-01 | cold call | hi-en | 3.2 | Codex Sol | 26 | 0 | 0 |
| fx-02 | inbound follow-up | mr-en | 4.6 | agy Gemini | 29 | 0 | 4 |
| fx-03 | demo | en-IN | 12.1 | Claude | 47 | 0 | 5 |
| fx-04 | objection-heavy | hi-en | 19.2 | Codex Sol | 42 | 3 | 5 |
| fx-05 | negotiation + close | mr-en | ~25 | agy Gemini | | | |
| fx-06 | lost deal | hi | 7.8 | Claude | 38 | 0 | 5 |
| fx-07 | callback | hi-en | 2.1 | Claude | 30 | 0 | 5 |
| fx-08 | multi-party (4) | hi-en | 28.9 | Codex Sol | 52 | 3 | 5 |
| fx-09 | demo | mr-en | ~40 | agy Gemini | | | |
| fx-10 | negotiation + close | en-IN | 22.7 | Claude | 59 | 3 | 5 |
| fx-11 | cold call | mr-en | 5.7 | Codex Sol | 26 | 0 | 3 |
| fx-12 | inbound follow-up | hi-en | 9.5 | agy Gemini | 37 | 0 | 9 |
| fx-13 | objection-heavy | en-IN | 14.8 | Claude | 57 | 3 | 7 |
| fx-14 | lost deal | mr-en | 13.0 | Codex Sol | 32 | 0 | 4 |
| fx-15 | multi-party | mr-en | ~20 | agy Gemini | | | |
| fx-16 | inbound follow-up | hi | 47.6 | Codex Sol | 60 | 3 | 4 |

Every call has `plan.json` (speakers, sections, 2–6 *coaching truths*: what the salesperson really did well or
badly, with turn ids), `script.json` (turns: `text` as a careful human transcriber would write it — Devanagari for
Hindi/Marathi, Latin for English words — and `tts`, the same words fully in one script with numbers spelled out),
and `facts.json` (25–60 facts, each with type, slot, value, normalised value, the turn ids, a **verbatim evidence
quote**, who said it, critical yes/no, needle depth, trap kind). Writers were three model families so no tested model
grades only its own family's writing. `check_call.py` gates every call: evidence must be found verbatim in the cited
turn; a needle appears in exactly one turn; 105–175 words per target minute; no Indian mobile numbers, emails, URLs,
PAN, Aadhaar-like or GSTIN patterns; no real brand names from a deny-list. Fictional names only; nothing was read
from any real call.

Trap kinds: `self_correction` (ground truth = corrected value), `alt_number_form` ("साढ़े बारह लाख" vs "12.5 L"),
`third_party_name`, `competitor_price` (must not be taken as ours), `retracted`, `ambiguous_speaker`.

## 5.2 Audio (GitHub Actions free runners, workflow `bench-tts`, refs `bench/**`)

- **Engines:** Kokoro-82M (Apache-2.0) — Hindi voices for Hindi and Indian-accented English (round-trip Whisper
  check: Indian English CER 2–20%, mostly digits written as words); **Marathi = Kokoro Hindi voices with the espeak-ng
  Marathi phonemiser** (Whisper-turbo tCER 0.37) instead of MMS-TTS Marathi (tCER 1.0, misheard as Gujarati).
  Four distinct voices (2 male, 2 female), per-speaker speed 0.92–1.12, pauses 150–700 ms, scripted overlaps.
  Limitation: Marathi has a Hindi accent; Indic Parler-TTS (native Marathi voices) needs an HF token on GitHub.
- **Variants per call:** `clean_16k` (mono), `stereo_16k` (salesperson left), `phone_8k` = 300–3,400 Hz band,
  pink + hum noise at SNR 8–20 dB, **G.711 μ-law** (Ubuntu's ffmpeg has no AMR-NB encoder), 8 kHz.
  `segments.json` gives every turn's true start/end for speaker scoring.
- TTS speech is more regular than real calls, so transcription scores are a *ranking*; real-speech public sets
  (IndicVoices, Kathbath-noisy, Svarah, MUCS) are the planned cross-check.

## 5.3 Harness (`harness/` on ac, API calls only, `nice -n 19 ionice -c3`)

- **Shape (a) "today"** is not re-implemented: the harness imports the product's own builders read-only from the
  dev workbench (`inference_tasks.prepare_fact_inputs` / `prepare_coaching_input`, `pointer_review.build_prompt` +
  `gemini_body`, `call_data.extraction.build_prompt` + `response_schema`, `call_data.classifier`) and sends exactly
  those requests to the model under test (C4 facts-v2 chunked, C5 coaching-v3 detailed overview, pointer review,
  call-data fast, deep extract, deep segment labels).
- **Shape (b)** one pass: one request, transcript once, one compact JSON with speakers, typed facts (+ segment ids),
  27 pointers, report (summary, strengths, improvements, missed opportunities, objections, closing, outcome, next
  step, 8 dimensions) and call type.
- **Shape (c)** audio in: the model hears the call and returns transcript + the same analysis in one answer;
  **(c′)** audio → transcript only, then (b) on any text model.
- **ASR arms:** Gemini audio (direct or via OpenRouter), Deepgram Nova-3 (`language=multi`, diarize), Sarvam
  saaras:v4 batch with diarization, AssemblyAI, Groq Whisper, ElevenLabs Scribe v2 (product's own settings),
  faster-whisper large-v3 / turbo on GitHub runners (CPU int8, real-time factor recorded).
- **Scoring:** facts by two LLM judges of different families (Gemini 3.8 Flash, Claude Haiku 5.5) against the fact
  sheet with the transcript as context (recall, critical/needle/trap recall, wrong-value rate, precision,
  hallucination = unsupported claims); reports by coverage of the planted coaching truths and count of false claims;
  ASR by **critical-fact retention** (LLM-judged, script- and number-format-invariant), plus CER, transliterated CER
  and speaker accuracy by time overlap; consistency = run-to-run pointer agreement; cost = receipts × list price.
- **Why CER alone misleads:** Sarvam wrote "सोलर रूफटॉप" and "₹2,20,000" for "solar rooftop" / "दोन लाख वीस हजार";
  the transcript is right, but CER calls it 54% wrong. Retention and end-to-end fact accuracy are the primary ASR
  metrics.
- **Budget guard:** every request in `results/ledger.jsonl` (provider, model, tokens, audio seconds, list and billed
  USD, latency — never content); OpenRouter refuses above $19 of the $20.
