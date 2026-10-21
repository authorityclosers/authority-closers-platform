# 7. Recommendation

## 7.0 Final recommendation (v2.0, 21 Oct, after the real calls and the Brain 4.0 rounds; supersedes 7.3–7.4)

All three pipelines transcribe with Gemini 3.1 Flash-Lite, measure pauses locally (free) and run ONE analysis pass
with the coaching lead's Brain 4.0 rubric that writes CRM facts, the 18 scores, 10–20 timestamped coach notes and the
report.

| | Lean (recommended) | Best coaching | Both, in parallel | Today |
|---|---|---|---|---|
| Analysis pass | GPT-6 Luna | Gemini 3.8 Flash | Luna (facts, scores) ‖ Gemini (coach notes, report) | Scribe + six Gemini 3.8 Flash stages |
| Facts found, fictional calls | 90.5% | ≈ 71% (one-pass prompt) | 90.5% | 68.4% |
| Unsupported facts | 3% | ≈ 5% | 3% | 4.0% |
| Coaching lead's notes covered, real calls | 40.7% (−5.2 [−10.8, +1.1]) | 50.0% (+4.0 [−1.8, +10.5]) | ≈ 50% | 46.0% |
| ₹/min standard (real calls) | **₹0.29** | ₹0.50 | ₹0.54 | ₹1.50 |
| ₹/min Flex / batch | **₹0.15** | ₹0.25 | ₹0.27 | — |
| From 1 Jan 2027 | unchanged | ₹0.75 / ₹0.38 | ₹0.80 / ₹0.40 | higher |
| Time after upload | ≈ 2.5 min | ≈ 2 min | ≈ 2.5 min | ≈ 4–5 min |

- **Lean** meets ≤ ₹0.40 at standard speed and ≈ ₹0.15 on Flex/batch (₹0.097 on a 13.8-min fictional call). It finds
  the most facts with the fewest unsupported ones and does not double in price in January; its coaching is about 5
  points behind today on the coaching lead's notes, which Brain 4.0 work and his annotated calls should close.
- **Best coaching** is the only pipeline ahead of today on the real calls.
- **≤ ₹0.10 on real calls** needs cheaper transcription: Flex (₹0.12), a compact transcript format, or self-hosted
  IndicConformer (≈ ₹0.02).
- **Before production:** the owner's approval of the data flows (audio to Google, transcripts to OpenAI;
  AC-GOV-AUD-001), a shadow week on staging, and AC-SVAL review before any Brain 4.0 score becomes official.

The sections below are the v1.0 recommendation from the fictional calls, kept for the record.


## 7.1 What the evidence supports, and what it does not

Supported (paired bootstrap over 16 calls, 95% intervals, Haiku judge; second judge agrees in direction):
- **One analysis pass is better than today's six** on the perfect transcript: Gemini 3.8 Flash one pass +10 points fact
  recall [+4, +17], +10 critical [+5, +16], +7 coaching coverage [+1, +12], no more unsupported facts; GPT-6 Luna
  +23 recall [+18, +28], coaching equal [−12, +2]. One pass is also steadier: 91% of pointer verdicts repeat run to run
  against ~70% for today's pointer review.
- **The one pass loses nothing against today on the same transcript** (6.7): fed the same Gemini 3.1 Flash-Lite
  transcripts, the 3.8 Flash one pass is level with today's six stages on every measure (recall +2.7 [−4.5, +10.3],
  unsupported facts +1.2 [−0.3, +2.9], coaching +1.7 [−6.4, +10.9]); GPT-6 Luna is far ahead on facts (+20.5
  [+16.5, +24.3]) with no more unsupported facts (−1.2 [−2.6, +0.1]).
- **Gemini hears Indian calls well.** On real Hindi/Marathi speech Gemini 3.1 Flash-Lite equals Sarvam (the best
  specialist); on the fictional phone calls it keeps 93% of critical facts (3.8 Flash 96%) against 76–81% for Deepgram,
  AssemblyAI and Whisper.

Not yet supported:
- **"No quality loss" from switching the transcriber.** From Flash-Lite transcripts, unsupported facts rise by 4.9
  points [+2.7, +7.3] against today on a *perfect* transcript, and today's own pipeline shows the same rise (0.3% →
  4.0%) on those transcripts: misheard words become facts whichever pipeline reads them. Scribe's errors were not
  measured, so **the Scribe control is the deciding experiment for the transcriber**, not for the one pass. Needle
  recall is inconclusive (24 needles; intervals ±25 points).
- **Flex prices** are list-price projections (half of standard); Flex was not called. Latency, fallback rate and real
  Flex availability must be measured.
- **Real calls.** Synthetic voices are cleaner than phone calls; FLEURS is read speech.

## 7.2 Tomorrow: safe steps (no new data flow, official scoring unchanged)

| Step | Effect at 13.8 min | Risk |
|---|---:|---|
| `serviceTier: "flex"` on every background Gemini call, retry then fall back to standard | ₹1.19 → ≈ ₹0.78 | latency 1–15 min |
| Stop the deep pipeline's per-segment LLM labels (unused by the report; 27% of the bill) | → ≈ ₹0.61 | none for users |
| Content-hash dedupe of re-analysis, no-op the 5-minute pointer timer on unchanged reports, compact repeated JSON, transcript-first prompts so the implicit cache can hit | a further few % | low |

These keep Scribe, so they cannot reach ₹0.40 (Scribe alone is ₹0.37).

## 7.3 The ≤ ₹0.40 pipeline: two owner decisions and one control experiment

```
audio ──► Gemini 3.1 Flash-Lite transcription (Flex) ──► transcript (C2 shape)
transcript ──► ONE Gemini 3.8 Flash pass (Flex, exhaustive-facts prompt): roles, facts, report
               + today's pointer review unchanged (official scoring stays as it is)
```

| | 4.5 min | 13.8 min | 60 min |
|---|---:|---:|---:|
| Projected, Flex, pointer review kept | ₹0.52 | ₹0.24 | ₹0.13 |
| Projected, Flex, pointers inside the one pass (after an AC-SVAL review) | ₹0.32 | ₹0.16 | ₹0.10 |
| Measured, standard tier, pointers inside the pass | ₹0.64 | ₹0.32 | ₹0.20 |
| From 1 Jan 2027 (Gemini 3.8 Flash ×2), Flex, pointers inside | ₹0.56 | ₹0.25 | ₹0.14 |
| From 1 Jan 2027, Flex, pointer review kept | ₹0.96 | ₹0.40 | ₹0.19 |

1. **Owner decision:** send real call audio to Google (paid tier, no training) — a new data flow under AC-GOV-AUD-001.
2. **Owner decision:** run the one pass in **shadow** next to today's pipeline on staging (no user sees it; official
   scores untouched) for a week, comparing facts, reports and Flex latency.
3. **Control experiment (≈ ₹100–200):** Scribe on the 16 fictional calls, and Scribe-vs-Gemini on ~20 staging staff
   calls with their stored transcripts and reports. If Gemini's unsupported-fact rate is within 1 point of Scribe's and
   critical facts are not lower, switch; otherwise keep Scribe and take only the one pass (₹0.55/min at 13.8 min).

The ₹0.40 target holds for calls of about 6 minutes and longer with the pointer review kept; for 4–5-minute calls it
needs the pointers inside the one pass, which is a scoring change for the AC-SVAL process.

## 7.4 The path to ≤ ₹0.10, and the durable choice after 1 Jan 2027

From the same Flash-Lite transcripts, GPT-6 Luna (one pass, first prompt) reached **88.9% fact recall, 88.6% critical,
87.5% needles, 2.8% unsupported facts and 72% coaching truths** — against today on a *perfect* transcript: +18 points
recall [+15, +22], +14 critical [+10, +17], coaching level [−9, +8], +2.5 points unsupported [+1.3, +3.9]. Measured
cost ₹0.031/min for the analysis; all-in ₹0.107 at 13.8 min with Flash-Lite on Flex, ₹0.089 with Luna on Flex too
(₹0.12 at 4.5 min, ₹0.078 at 60 min). Luna's price does not double in January; Gemini 3.8 Flash's does, which pushes
the Gemini-analysis pipeline back to ₹0.56/min on 4.5-minute calls. **Luna is the stronger and the durable analysis
model**; Gemini 3.8 Flash only wins on coaching wording (79% vs 72%).

Before Luna carries real calls: OpenAI's provider gate (retention, region, training use, DPA; the product's C5 code can
already call it), measured Flex pricing for OpenAI, a coaching prompt to close the 7-point coaching gap (the exhaustive
prompt did not: 62%), and the same Scribe control. Self-hosting transcription (IndicConformer; Whisper turbo was too
weak on Marathi) would keep audio inside AC and cut it to ≈ ₹0.01–0.02/min, at the price of running a CPU box.

## 7.5 Not recommended

- Gemini Flash-Lite models writing the analysis (33–50% recall).
- Audio → Flash-Lite → everything in one call (23% recall).
- Distilling the per-segment labels into a local classifier (33–61% agreement on 1,253 segments, near the
  majority-class baseline): drop the labels instead.
