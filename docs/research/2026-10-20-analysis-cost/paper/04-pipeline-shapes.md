# 4. Pipeline shapes and their cost (design estimates; quality to be measured)

Cost model (`costmodel.py`): `cost(call) = STT(m) + Σ_stages [(I_fix + I_var·m)·p_in·(1 − h·(1 − r)) + (O_fix + O_var·m)·p_out]`
with h = cache-hit share of input, r = cached price ratio (0.1 on Gemini), and flex/batch halving p.
Today's token shapes are measured (section 1); the others are estimates to be replaced by phase-3 receipts.

| Shape | What changes | ₹/min @ 4.5 min | @ 13.8 min | @ 60 min |
|---|---|---:|---:|---:|
| **a** today (Scribe + 3.8 Flash, 6 transcript reads) | — | 1.93 | 1.19 | 0.91 |
| a + Flex on every Gemini call | `service_tier: flex` (50% off, 1–15 min latency, best effort) | 1.15 | 0.78 | 0.64 |
| a, every stage on 2.5 Flash-Lite | model switch only | 0.54 | 0.46 | 0.43 |
| **b** Scribe + one text pass, 3.8 Flash | one JSON with facts + pointers + report + call data | 0.87 | 0.58 | 0.47 |
| b Scribe + one pass, 2.5 Flash-Lite | | 0.42 | 0.39 | 0.38 |
| **c** audio → one call, 3.8 Flash (writes transcript + analysis) | no Scribe | 0.82 | 0.53 | 0.43 |
| c audio → one call, 3.1 Flash-Lite | | 0.36 | 0.25 | 0.21 |
| c audio → one call, 2.5 Flash-Lite | | 0.13 | **0.10** | 0.09 |
| c audio → one call, 2.5 Flash-Lite, flex/batch | | 0.07 | **0.05** | 0.04 |
| **c′** 2.5 FL audio → transcript, then one text pass on 3.8 Flash | keeps the strong model for analysis | 0.58 | **0.29** | 0.19 |
| c′ 2.5 FL audio → transcript, then one pass 2.5 FL | | 0.14 | 0.10 | 0.09 |
| **d** Scribe + hybrid (local labels/features, LLM writes facts + wording), 3.8 Flash | deep labels and stats leave the LLM | 0.69 | 0.51 | 0.44 |
| d 2.5 FL audio → transcript + hybrid on 2.5 FL | | 0.12 | **0.10** | 0.09 |
| new providers*: Groq Whisper turbo + one pass DeepSeek V4.1 Flash (cheapest host) | | 0.08 | 0.07 | 0.07 |
| new providers*: Groq Whisper turbo + one pass Haiku 5.5 | | 0.13 | 0.10 | 0.08 |

\* New providers need the AGENTS.md / AC-GOV-AUD-001 gates before any real call goes to them.

**What the table says before any quality data:**
1. **Scribe sets a floor of ₹0.367/min.** With Scribe kept, even the cheapest text model leaves ~₹0.38–0.42/min. The
   ₹0.40 target needs either Scribe replaced, or Scribe plus almost-free text processing.
2. **Inside Google alone** (no new provider): Gemini audio-in on Flash-Lite for the transcript, plus a single text
   pass, lands at **₹0.10–0.29/min** depending on which model writes the analysis; flex halves the Gemini part.
3. **Fixed per-call cost matters as much as per-minute cost** for short calls: today's ₹4.97 per call is mostly four
   fixed-size JSON outputs. A single pass with one compact output is the biggest structural cut.
4. The **₹0.10 target is reachable on paper only by Flash-Lite-class audio-in (Google) or by new providers** (Groq
   Whisper + a cheap open-weight text model). Which one holds quality is exactly what phase 3 measures.

## 4.1 Shape (d): what non-LLM "decision models" can and cannot do

| Job | Today | Non-LLM replacement | Expected quality | Verdict |
|---|---|---|---|---|
| Talk ratio, talk time, pace (wpm), pauses, overlaps/cut-ins, longest monologue, loudness, pitch | already local (AudioAtlas C1, `call_metrics.py`, `call_data/audio.py`) | — | measured, exact | **keep local; never ask an LLM** |
| Per-segment act (question/answer/commitment…), sentiment (3-way), intent (16), tone (8), topics — **the deep pipeline's segment labels, an LLM call today (₹0.2–0.3/min)** | Gemini prompt (`call_data/classifier.py`) | multilingual sentence embeddings (e.g. EmbeddingGemma-300m, multilingual-e5-small, LaBSE/MuRIL) + logistic regression / LightGBM heads, trained on LLM-labelled segments (distillation), human-checked sample | act and sentiment ≈ 80–90% agreement with the LLM labeller; 16-way intent ≈ 70–85%; tone ≈ 60–70% (literature on intent/dialogue-act classification; to be measured) | **replace**, keep the LLM only for low-confidence segments (cascade) |
| Call type (cold call / follow-up / demo…), stage of the deal | rules (`call_type.py`) + LLM | same embeddings + classifier over the first minutes + metadata | ≈ 85–90% for coarse classes | **replace** |
| Entity spans: names, money (lakh/crore), dates, quantities | LLM | multilingual NER (GLiNER-multi, IndicNER) + rule normalisers for Indian numbers | high recall on spans, weak on *roles* ("whose budget?") | **use as a grounding guard**: every number/name in the report must exist in the transcript's spans (cuts hallucination, M4) |
| Relational facts (who promised what by when; budget vs competitor price; self-corrections), coaching wording, missed opportunities, summary | LLM | none reliable | — | **LLM still needed**, but it can read one compact pass instead of six |
| Emotion / "tone" from the waveform | — | SSL audio encoders (WavLM, Whisper encoder, emotion2vec) + heads | weak on 8 kHz Indian phone audio; and AC-SVAL forbids official feelings scores | research only |

**On "Jev".** Two readings, both covered:
- *JEPA-style embeddings:* I-JEPA / V-JEPA are image and video models; audio JEPA variants (A-JEPA) are research
  checkpoints trained on English/AudioSet, not on Indian phone speech. There is nothing production-ready to adopt.
  The practical equivalent is the self-supervised encoder + small-classifier stack above, which is proven.
- *TypeSafe Jev (owner's 30 Sep definition):* now on OpenRouter as `typesafe/jev-router`, a "System One" router that
  picks a model and effort per request; price is per routed model. It is a new external provider (gates apply),
  and its routing makes cost per call unpredictable. It can be one benchmark arm on fictional calls if wanted.
