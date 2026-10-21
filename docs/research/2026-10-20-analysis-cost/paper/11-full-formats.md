# 11. GPT-6 Luna in the product's full formats, and the ₹0.10 configuration (round 8, 21 Oct 2026)

## 11.1 What ran

- **Requests:** the one-pass build's own two requests, from `ac_platform.one_pass.analysis` pinned at workbench
  8fced2da as `harness/op_analysis.py`: *facts* (call data, notes for the C4 packet, the 27-pointer review) and
  *report* (C5 coaching-v5). The answers went through the product's own validators: C4 fact packet, C5 report,
  pointer review, call objects.
- **Luna:** OpenAI's API directly, through the bench project (fictional calls only, `store: false`).
- **Gemini report (hybrid):** the one-pass report request on Google AI Studio via OpenRouter.
- **Transcripts:** the 16 fictional calls' Gemini 3.1 Flash-Lite transcripts, the same ones today's six stages read.
- **Judge:** Claude Haiku through the Claude subscription CLI (`claude-sub/haiku`, no API spend) for every arm,
  today's included.

Variants (facts request / report request):

| Variant | Facts | Report |
|---|---|---|
| Base | Luna | Luna |
| Report-depth | base's facts | Luna, plus a report-depth instruction |
| Report-depth, reasoning high | base's facts | Luna, report-depth instruction, reasoning effort high |
| Hybrid | base's facts | Gemini 3.8 Flash |
| Flex | Luna, OpenAI Flex tier | Luna, OpenAI Flex tier |

## 11.2 Results (16 fictional calls; difference vs today on the same transcripts, 95% interval)

| Pipeline | Fact recall | Unsupported | Coaching truths | C5 / pointers valid | ₹/min standard, 4.5 / 13.8 / 60 min | Time per call |
|---|---|---|---|---|---|---:|
| *Today: six Gemini 3.8 Flash stages* | *60.7%* | *2.9%* | *81.4%* | — | *₹1.98 / 1.03 / 0.67* | 3–4 min |
| Luna, full formats | 62.1% (−0.5) | 1.9% | 78.6% (−4.1 [−17.9, +9.8]) | 94% / 100% | ₹0.36 / 0.22 / 0.16 | 96 s |
| **Luna, report-depth prompt** | 72.6% (+11.9 [0.0, +22.7]) | 1.7% | 78.8% (−2.5 [−11.6, +4.5]) | **100% / 100%** | ₹0.36 / 0.22 / 0.17 | 65–96 s |
| Luna, report-depth, reasoning high | 69.3% (+8.6) | 2.4% | 77.1% (−4.2) | 88% / 100% | ₹0.43 / 0.24 / 0.17 | 164 s |
| **Hybrid: Luna facts + Gemini report** | 78.5% (+17.8 [+8.1, +26.8]) | 2.7% | **85.6% (+4.2 [−4.2, +12.3])** | 94% / 100% | ₹0.58 / 0.31 / 0.21 | 96 s |
| Gemini 3.8 Flash one pass (one-pass build, its own transcripts) | 73.6% (+13.0) | 3.0% | 37.3% overall; 73.3% vs 76.7% on the 9 calls with a report | 56% / 100% | ₹1.38 / 0.57 / 0.27 | 84 s |
| **Flex: Luna (both requests) + Flash-Lite on Flex** | same model as base | | | 81% / 100% | **₹0.18 / 0.11 / 0.08** | 261 s |
| Hybrid, all on Flex | | | | | ₹0.29 / 0.16 / 0.10 | ≈ 4–5 min |

**Facts need a careful reading.** Base, report-depth, reasoning-high and hybrid share the same Luna facts answer.
The subscription judge scored that one answer at 62.1%, 72.6%, 69.3% and 78.5% recall (mean 70.6%; critical facts
mean 72.6%; unsupported 2.2%). The CLI judge has no temperature control and varies by about ±8 points on identical
input. Luna's facts are therefore about 10 points above today's on the same transcripts (60.7%, one judgement), but
fact differences under about 10 points cannot be resolved with this judge. The API Haiku judge (temperature 0)
scored today's facts 68.4% and its coaching 77.1%, so judges must never be mixed across arms.

## 11.3 Findings

1. **Luna writes every product format correctly.** With the report-depth instruction, all 16 C5 reports and pointer
   reviews passed the product's validators. Base and Flex failed C5 on 1–3 calls; that is run-to-run variance, and a
   retry covers it. The one-pass build's Gemini run (its earlier JSON-mode design) lost 7 of 16 reports.
2. **Luna's report is within noise of today's** (−2.5 points with the report-depth prompt). Reasoning effort high did
   not help (−4.2) and costs 70% more time. **A Gemini report on top of Luna's facts is the best coaching measured**
   (+4.2), for ₹0.09 a minute more at 13.8 minutes.
3. **Output dominates the cost: 12–13k output tokens a call**, at Luna's $0.50/M against Gemini 3.8 Flash's $4.125/M.
   That is why the Gemini full-format run costs ₹0.57 a minute and Luna's ₹0.22.
4. **OpenAI Flex works for Luna:** all 32 requests were served on Flex with no fallback, at half price and about 4.4
   minutes a call instead of 1.6.
5. **Reliability:** one of 36 standard Luna report requests ran away (48,000 reasoning tokens, `finish: length`, no
   answer). Production needs `max_completion_tokens` of about 20k and one retry.

## 11.4 The ₹0.10 production configuration

**Gemini 3.1 Flash-Lite transcription on Gemini Flex + GPT-6 Luna on OpenAI Flex** for both one-pass requests
(facts; report with the report-depth instruction), in the background:

- **Cost:** ₹0.108 a minute on a 13.8-minute fictional call, ₹0.083 on a 60-minute call, ₹0.18 on a 4.5-minute call.
- **Time:** ready in about 5–10 minutes (Flex answers within 15).
- **Safeguards:** cap output at about 20k tokens with one retry; fall back to the standard tier after about 10 minutes.

Two caveats:

- Real calls are denser. Flash-Lite transcription alone is ₹0.12 a minute on Flex there, so the same configuration
  is about ₹0.15. Reaching ₹0.10 on real calls takes a compact transcript format (fewer output tokens) or
  self-hosted transcription.
- If coaching quality must beat today's from day one, the hybrid on Flex (Gemini writes the report) costs ₹0.155 a
  minute at 13.8 minutes.

Real calls go to OpenAI only after the DPA and the privacy-page update (owner approval of 21 Oct, conditions
pending).
