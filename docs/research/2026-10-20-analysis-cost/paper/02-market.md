# 2. Market (prices read live on 20 Oct 2026)

Sources, all read 20 Oct 2026: Google Gemini pricing, audio, caching, flex-inference, rate-limit and deprecation
pages (ai.google.dev); OpenRouter public `GET /api/v1/models` and per-model `/endpoints` (JSON saved in
`market/live/`); ElevenLabs API pricing; Groq models + speech-to-text docs; Deepgram, AssemblyAI and Sarvam pricing
pages; DeepSeek and Z.ai pricing docs. ₹ at ₹100/$ (Admin sheet). "Cheapest reputable" = first party or a large
host at fp8 or better; OpenRouter's headline price is often an fp4-quantised small host with unknown data terms,
shown separately.

## 2.1 Transcription and audio input (per audio minute)

| Option | $/min list | ₹/min | Diarization | Hindi / Marathi / code-mix | Free credit | Status for us |
|---|---:|---:|---|---|---|---|
| **ElevenLabs Scribe v2** (today) | 0.00367 ($0.22/h) | 0.367 | yes | auto language; Devanagari output (50% of our transcript chars) | 4.5 h/month on the free plan | in use |
| Deepgram Nova-3 multilingual | 0.0052 (Growth 0.0043) | 0.52 | included | `language=multi`; Hindi yes, Marathi not listed | $200, never expires | **built in code** (`deepgram/nova-3`) |
| AssemblyAI Universal-2 (+diar.) | 0.00283 ($0.15+0.02/h) | 0.28 | +$0.02/h | to verify | $50 | not built |
| AssemblyAI Universal-3.5 Pro (+diar.) | 0.00383 | 0.38 | +$0.02/h | to verify | $50 | not built |
| Sarvam batch (+diarization), pay-as-you-go | ₹0.49 (₹0.59) | 0.49–0.59 | +₹0.10 | Indian languages first | "free credits on sign-up" | planned in registry |
| Groq Whisper large-v3 | 0.00185 ($0.111/h) | 0.185 | **no** | multilingual (Whisper hi/mr; code-mix weak) | free tier (rate-limited) | not built |
| **Groq Whisper large-v3-turbo** | **0.00067** ($0.04/h, min 10 s) | **0.067** | **no** | as above, WER 12% vs 10.3% (Groq's figure) | free tier | not built |
| Gemini 3.5 Transcribe | 0.003 audio + 0.002 text | 0.50 | ? | ? | free tier | — (dearer than Scribe) |
| **Gemini 3.8 Flash, audio in** | 0.00144 in (flex 0.00072) + output | 0.144 + out | prompt-driven | strong; to be measured | free tier (bench) | **Google is already our provider** |
| Gemini 3.1 Flash-Lite, audio in | 0.00096 (flex 0.00048) + output | 0.096 + out | prompt-driven | to measure | free tier | Google |
| **Gemini 2.5 Flash-Lite, audio in** | **0.00058** (flex/batch 0.00029) + output | **0.058** + out | prompt-driven | to measure; no shutdown date announced | free tier | Google |
| Self-hosted faster-whisper turbo (GPU rented by the hour) | ≈ 0.0001–0.0003 | ≈ 0.01–0.03 | add pyannote | as Whisper | — | ops cost, not ac (CPU-bound, disk 99%) |

Gemini audio facts (Google audio doc): **32 tokens per second (1,920 per minute), up to 9.5 h per prompt, any
channel count is mixed to mono, downsampled to 16 kbps; diarization and MM:SS timestamps are prompt-driven, with no
stated accuracy.** Output is capped at 65,536 tokens per response, so a 60-min transcript with speakers and times
(~35–40k tokens) fits, but chunking at 15–20 min is safer.

**The owner's question — can Gemini 3.8 Flash take the audio itself and skip transcription? Yes.** It accepts
audio natively (Google docs; OpenRouter lists audio input at the same $0.75/M as text). Cost: the audio is
₹0.144/min in, plus whatever we ask it to write. Writing the transcript back (we need one for the product) costs
~560 output tokens/min × $3.75/M = ₹0.21/min on 3.8 Flash, so "audio-in" on 3.8 Flash is ₹0.35/min before any
analysis — no cheaper than Scribe. It becomes cheap only on Flash-Lite (2.5 FL: ₹0.058 in + ₹0.022 out ≈ ₹0.08/min)
or Flex (half). Risks to measure: diarization of 2–4 speakers, timestamp drift on long audio, "cleaning up"
code-mix or translating it, dropped or invented words in noise/silence, and Hindi/Marathi script choice.

## 2.2 Text models (per 1M tokens, USD)

| Model | Reputable price in / out | Cache read | Flex / batch | Cheapest seen (host, quant) | Context | Strict JSON | Audio in | Notes |
|---|---|---:|---|---|---|---|---|---|
| **Gemini 3.8 Flash** (today) | 0.75 / 3.75 (→1.50/7.50 on 1 Jan 2027) | 0.075 | **flex 0.375 / 1.875**; batch same | — | 1M | yes | yes | implicit cache ≥ 4,096-token prefix |
| Gemini 3.5 Flash-Lite | 0.30 / 2.50 | 0.03 | flex 0.15 / 1.25 | — | 1M | yes | yes (0.30) | |
| Gemini 3.1 Flash-Lite | 0.25 / 1.50 | 0.025 | flex 0.125 / 0.75 | — | 1M | yes | yes (0.50) | shutdown earliest 7 May 2027; failed the 17 Oct pointer replay (46% vs 70% agreement) |
| **Gemini 2.5 Flash-Lite** | **0.10 / 0.40** | 0.01 | flex/batch 0.05 / 0.20 | — | 1M | yes | yes (0.30) | GA, "no shutdown date" |
| Claude Haiku 5.5 | 0.10 / 0.50 (prompt ≤ 100k) | 0.01 | batch 0.05 / 0.25 | — | 1M | yes | no | new provider |
| GPT-6 Luna | 0.10 / 0.50 | 0.01 | flex 0.05 / 0.25 | — | 1.05M | yes (strict) | no | **already coded for C5** (`openai_tasks.py`) |
| DeepSeek V4.1 Flash | first party 0.30 / 1.20 peak, **0.15 / 0.60 off-peak**; DeepInfra fp8 0.14 / 0.42 | 0.003–0.006 | DeepInfra flex 0.112 / 0.336 | 0.028 / 0.12 (OpenInference, fp4) | 1M | JSON | no | China-based first party; hosts in US |
| GLM-5.3 Flash | 0.15 / 0.50 (Z.ai, Together, Fireworks) | 0.03 | — | 0.048 / 0.16 (fp4) | 1M | yes | no | GLM-4.7-Flash is **free** on Z.ai |
| Qwen 3.8 Flash | 0.15 / 0.47 (Alibaba) | 0.016 | — | — | 1M | yes | omni variant: yes | |
| Qwen 3.7 Flash | 0.03 / 0.13 (Alibaba) | 0.006 | — | — | 1M | no schema flag | no | |
| Xiaomi MiMo V2.6 Flash | 0.14 / 0.28 (Xiaomi) | 0.0028 | — | 0.03 / 0.08 (fp4) | 1M | yes | **yes** | output price is the lowest of the strong models |
| gpt-oss-120b | 0.15 / 0.60 (Groq); 0.09 / 0.36 (Vertex) | 0.075 | — | 0.03 / 0.15 (fp4) | 131k | yes | no | **already coded for C4 via Groq** |
| gpt-oss-20b | 0.075 / 0.30 (Groq) | — | — | 0.018 / 0.09 | 131k | yes | no | |
| Mistral Small 2603 | 0.15 / 0.60 | 0.015 | batch 0.075 / 0.30 | — | 262k | yes | no | |
| Llama 4 Scout | 0.10 / 0.30 | — | — | — | 1.3M | yes | no | |
| Kimi K2.6 / K3 | 0.65 / 3.41; K3 0.24 / 11.9 | | | | | | | too dear on output |
| Sarvam-hosted (India): DeepSeek V4.1 Flash / GLM-5.3 Flash / Sarvam 105B | ₹25/₹105, ₹13.5/₹45, ₹15/₹60 per M | ₹0.5–5 | — | — | | | | **India-hosted** option if residency matters |

**Independent cross-check (Codex Sol 6.1 market scan, same day, 364 sources fetched, `market/llm-market.md`):**
same prices within rounding; shortlist for the benchmark = Haiku 5.5, GPT-6 Luna, MiMo V2.6 Flash, DeepSeek V4.1
Flash (1017 snapshot), GLM-5.3 Flash, Qwen 3.7 Flash, Qwen 3.8 Flash, gpt-oss-120b. Published evidence it found:
Artificial Analysis long-context reasoning (AA-LCR) Haiku 5.5 high 77%, GPT-6 Luna max 83%; AA Intelligence Index
MiMo V2.6 Flash 38, GLM-5.3 Flash 42; the SOB structured-output benchmark shows ~80% *value* accuracy for the best
small models even when the JSON is valid ("the JSON is valid, but the values are not" — HN). No public result covers
Hindi/Marathi code-mix fact extraction, hence our own benchmark.

Free sources (Codex's live checks): Gemini free tier (limits per project, shown in AI Studio); Groq free LLM tier is
30 RPM / 8,000 TPM — too small for a whole transcript in one request; OpenRouter `:free` models 20 RPM / 50 RPD
(1,000 RPD once ≥ $10 has been bought, which the $20 credit does); Z.ai GLM-4.7-Flash and GLM-4.5-Flash are free;
Cohere evaluation key 1,000 calls/month. Not available: GitHub Models (retired 30 Jul 2026), Cerebras (only a $5 /
30-day trial with a card), Hugging Face (no monthly credits for free accounts).

**FX.** ECB reference rates (20 Oct) give ₹94.93/$; a market quote gave ₹96.5. Every ₹ in this paper uses the Admin
sheet's ₹100/$, so real rupee costs are 3.5–5% lower than shown.

**About "Jev".** OpenRouter lists `typesafe/jev-router`: "Jev Router picks the best model and reasoning effort for
each request… It runs on Jev, TypeSafe's first System One model". The owner defined "Jev" on 30 Sep as TypeSafe AI's
calibrated fast decision model (memory note); the brief for this study reads it as JEPA-style embeddings plus
classic decision models. Section 4 covers both readings.
