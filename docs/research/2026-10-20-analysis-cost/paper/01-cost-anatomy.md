# 1. Cost anatomy of today's pipeline (measured 20 Oct 2026)

**Data.** Read-only SQL on dev (`ac_dev_live`) and staging through `~suyash/costq/q.sh` (forced read-only). Every
recording ≥ 60 s with a C4 and a C5 receipt, canary fixtures excluded: staging 35 recordings / 457 audio min,
dev 39 / 502 min (dev holds a copy of staging up to ~10 Oct, so the two overlap; staging is quoted). Tokens are the
provider receipts (`jobs.provider_receipt->usage`, `conversation_pointer_reviews.*_tokens`,
`call_data_runs.*_tokens`). No production row was read. Queries: `costq/anat2.sql`, `costq/fit.sql`.

**Prices.** Gemini 3.8 Flash $0.75 / $3.75 per M tokens (Google pricing page, read live 20 Oct; doubles to
$1.50 / $7.50 on 1 Jan 2027), Scribe v2 $0.22 per audio hour (ElevenLabs API pricing page, read live). Rupees at the
Admin price sheet's ₹100/$ (`admin_pricing._FX_USD_TO_INR`); the live rate is ≈ ₹96.5/$, so real rupee cost is
≈ 3.5% lower than every ₹ figure here.

## 1.1 Each paid stage is "fixed per call + per audio minute"

Per-recording linear fit, tokens = a + b × audio minutes (staging, n = 24–35; dev agrees within ~10%):

| Stage | Input fixed | Input / min | Output fixed | Output / min | R² (in) | Reads the transcript |
|---|---:|---:|---:|---:|---:|---|
| Transcript itself (for scale) | — | ≈ 408 tok (971 chars, 50% Devanagari, 0.42 tok/char) | | | 0.96 | — |
| C4 facts (1 call per ~5 min chunk) | ≈ 0 | 735 | 92 | 60 | 0.89 | 1× + per-chunk prompt |
| C5 report / coaching | 4,122 | 617 | 3,456 | 37 | 0.90 | 1× + C4 facts |
| Pointer review | 792 | 419 | 4,187 | 3 | 0.92 | 1× |
| Call data — fast | 1,263 | 400 | 1,761 | 7 | 0.93 | 1× |
| Call data — deep | 965 | 807 | 2,342 | 519 | 0.93 | ≈ 2× |
| **All LLM stages** | **7,142** | **2,978** | **11,838** | **626** | | **≈ 6× per call** |

Thinking tokens: 0 on every receipt. Cached tokens: 0 on every receipt (no context caching, no batch).

## 1.2 What that costs

| Per call | ₹ (at ₹100/$) | $ |
|---|---:|---:|
| Fixed LLM cost per call (prompts + fixed-size outputs) | **₹4.97** | $0.0497 |
| — of which output tokens | ₹4.44 | $0.0444 |
| Variable LLM cost per audio minute | ₹0.458 | $0.00458 |
| Scribe v2 per audio minute | ₹0.367 | $0.00367 |
| **Variable all-in per audio minute** | **₹0.825** | $0.00825 |

`cost(call) = ₹4.97 + ₹0.825 × minutes`, so the cost *per minute* depends on call length:

| Call length | Today, all stages | Without call-data fast + deep (pre-19 Oct shape) |
|---|---:|---:|
| 4.5 min (19 Oct production staff import average) | ₹1.93/min ($0.0193) | ₹1.26/min |
| 13.8 min (Oct staging/dev average) | ₹1.19/min ($0.0119) | ₹0.77/min |
| 60 min (owner's 23 Sep example) | ₹0.91/min = ₹54.5 per call | ₹0.59/min = ₹35.5 per call |

**Check against the owner's figure.** The owner's longest call (23 Sep, ~60 min) cost ₹21 for transcription and
₹33.66 in all (₹0.56/min, ~1.1 lakh tokens). The model above, in the pipeline shape of 23 Sep (no call-data engine),
predicts ₹22.0 + ₹13.5 = ₹35.5 and ~1.24 lakh tokens: within 5%. So the model is sound, and it shows that **since
the call-data engine went live (fast 19 Oct, deep 19 Oct "yes deep") a typical call costs about ₹1.2/min, about twice
the ₹0.56–0.63 quoted today.** Deep alone is ₹0.32/min of a 14-min call.

## 1.3 Where the money goes (13.8-min call, ₹16.4 in all)

| Stage | ₹ per call | Share | Main driver |
|---|---:|---:|---|
| Scribe v2 transcription | 5.06 | 31% | per-minute list price |
| Call data — deep | 4.47 | 27% | 519 output tokens per audio minute (segment labels) + 2× transcript read |
| C5 report / coaching | 2.44 | 15% | ~3.5k-token fixed report output; 4.1k-token fixed prompt |
| Pointer review | 2.08 | 13% | ~4.2k-token fixed output |
| Call data — fast | 1.21 | 7% | 1.8k-token fixed output |
| C4 facts | 1.11 | 7% | transcript read in 5-min chunks with a prompt each |

On a 4.5-min call the fixed parts dominate: Scribe is only 19%, and C5 + pointer review + fast + deep are 76%.

## 1.4 What each paid call sends (code study of the dev workbench, file:line in `anatomy/`)

| Stage | Model (where set) | Input | Output | Retries | Settings |
|---|---|---|---|---|---|
| C2 transcription | ElevenLabs `scribe_v2` (approval route; Deepgram `nova-3` is the only other built route) | the original upload, unchanged: no resampling, no mono mix, no silence trim, no channel split; `diarize=true`, word timestamps, language auto | word timings merged into segments (same speaker, gap ≤ 1.5 s, < 700 chars) | person-triggered only | — |
| C4 facts | Gemini 3.8 Flash (or Groq gpt-oss-120b / Llama 3.3 70B) | transcript chunks (~16 KB each: ~10–12 min of English, **~5–7 min of Devanagari**, 3 bytes/char), ≈ 2.7K-char system prompt **resent per chunk**, no schema | `{overview, observations[≤6], uncertainties[≤2]}`, cap 1,400 tokens | none automatic | thinking LOW, **no temperature**, JSON mode |
| C5 report | Gemini 3.8 Flash (or Groq, OpenAI gpt-6-luna/sol) | system: voice rules + qualitative pack (6 KB) + overview rules (~5 KB) + Dipak profile JSON (10 KB); user: **whole transcript** + merged C4 facts; plus `responseJsonSchema` (~8 KB) | v4 report (summary, strengths, improvements, missed opportunities, objections, closing, verdict, 8 dimensions, overview), cap 3,200 | **1 automatic repair = the whole request again** | thinking LOW, no temperature |
| Pointer review | Gemini 3.8 Flash, hard-coded | ≈ 7.5K-char system with 27 pointer rows + **whole transcript** + schema | 27 pointers × 7 fields + outcome + qualification + prospect profile, cap 10,000 | 2 attempts | thinking LOW; timer every 5 min |
| Call data fast | Admin (default 3.8 Flash) | ≈ 5–6K-char system (33 fact types) + **whole transcript** + schema | typed facts + speaker roles, cap 12,000 | 2 attempts | **temperature 0.1**, thinking LOW |
| Call data deep extract | Admin deep model | same with 34 deep types + **whole transcript** | typed facts | 2 attempts | same |
| Call data deep labels | same | **whole transcript in 120-segment windows** (+4 context each side) | one label object per segment (intent 16-way, act, sentiment, tone, topics) | shared | same |

Local (free) stages already compute what an LLM should never be asked for: AudioAtlas C1 (14 frame features at
10 ms: RMS, dBFS, clipping, spectral shape, f0, periodicity), `call_metrics.py` (talk share, questions per minute,
cut-ins, longest monologue, price moments), `call_data/audio.py` (per-role talk time, pace wpm, loudness, pitch,
pauses ≥ 1.5 s, overlaps). C5 receives none of the acoustic features today (`acoustic_measurements_supplied: False`).

**Three structural facts drive the redesign:**
1. **Output tokens are 68% of LLM spend** ($3.75/M vs $0.75/M). Four stages each write a fixed 1.8–4.2k-token JSON.
   On a short call the fixed outputs alone (₹4.44) exceed the whole ₹0.40/min target for an 11-min call.
2. **The transcript is read about 6 times** (C4, C5, pointer review, fast, deep ×2), always uncached.
3. **Transcription alone is ₹0.367/min**, already 3.7× the ₹0.10 long-run target, so no text-model change can reach
   ₹0.10 while Scribe v2 stays.
