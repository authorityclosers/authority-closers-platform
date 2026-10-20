# Sales X-Ray one-pass analysis (Google only), beside today's pipeline

Design v1, 21 Oct 2026. Owner: "start building the Google-only one-pass pipeline
(Gemini 3.1 Flash-Lite transcription plus one Gemini 3.8 Flash pass) on dev now,
behind the Admin provider switch, compared side by side with today's pipeline
before any production change."

Code: `packages/python/ac_platform/one_pass/`. Admin: `/sales-xray/one-pass`.

## Why

The cost research (20 Oct 2026, 16 fictional calls, two judges) measured:

| | fact recall | coaching truths covered | ₹ per audio minute |
|---|---|---|---|
| Today (Scribe + six Gemini 3.8 Flash reads) | 70.6% | 72% | about 1.19 all-in for a 14-minute call |
| One Gemini 3.8 Flash pass | 80.7% | 78.8% | 0.155 for the language model |

Gemini 3.1 Flash-Lite transcription tied the best Indian-language speech-to-text on
real Hindi and Marathi at ₹0.14 a minute (₹0.07 on Flex).

## What runs

```
today's C2 transcript saved ─► admitted (consent, retention, erasure, newest)
   ─► the AI spend guard (feature one_pass) ─► 'running' row committed
   ─► the call's stored audio as mono 32 kbps MP3
   ─► Gemini 3.1 Flash-Lite: speaker-labelled, timed segments ─► C2 contract
   ─► one Gemini 3.8 Flash read ─► call_data + notes + review + report
   ─► each part checked by its own stage's validator ─► outcome row
```

1. **Transcription** (`transcription.py`). The research's prompt and schema. Times
   (MM:SS) are normalised: ordered, at least 300 ms, inside the call. Speakers
   become `speaker_0`, `speaker_1` in order of first speech. The result is today's
   C2 shape and passes the Report's own transcript validator.
2. **One pass** (`analysis.py`). The system prompt is the product's own: the C5
   coaching-v5 prompt as the C5 stage builds it, the call data extraction's
   instructions and the pointer review's. One answer, four parts, each in its
   stage's wire shape:

   | part | checked by | becomes |
   |---|---|---|
   | `call_data` (every model type) | `call_data.extraction` | call objects (fast and deep), prospect facts |
   | `notes` | `reports.parse_fact_packet` | C4 facts, with the call objects |
   | `review` | `pointer_review.parse_review` | the pointer review |
   | `report` | `reports.parse_report_draft` (coaching-v5) | the C5 report and coaching |

   So Report, Prospect, Coaching, the call map and the lead card can read a one-pass
   result without change. Lean output: the prospect profile's facts come from the
   call data facts (not written twice); per-segment labels are not part of the pass.
   The instructions are the same for every call and come first, so Gemini's
   implicit cache can reuse that prefix; one read per call leaves nothing else to
   cache.
3. **Tiers.** Standard or Flex per stage (Admin). Flex is half price, best effort,
   may queue for minutes; after three busy answers a request falls back to standard
   once, and the run records `flex_fell_back`.

## The switch (Admin → One-pass trial, and All settings)

| mode | what happens |
|---|---|
| `classic` | today's pipeline only. The default everywhere |
| `both` | today's pipeline, and one pass beside it on each new call. People see today's |
| `one_pass` | people see one-pass results. Not offered yet: publishing comes after the comparison |

Development only: staging and production refuse anything but `classic` (code rule),
so no production approval or sealing changes. Production's switch is the owner's
decision.

## Money

Every request goes through the AI spend guard as feature `one_pass`. Its cap starts
at ₹0 in every environment; raising it in Admin → AI spend is the recorded approval.
Development's background AI must also be on. The ledger reads `one_pass_runs`: one
line per stage (Flash-Lite with its audio minutes, the 3.8 Flash pass), a start
without an outcome counts ₹2. Rupees are list prices (`pricing.py`, read 20 Oct
2026; 3.8 Flash doubles on 1 Jan 2027), Admin only, never on a user screen.

## Data

Migration `20261021_0116` (backup parity v83), both append-only:

- `analysis_pipeline_settings`: revisions of the switch, audited with the reason.
- `one_pass_runs`: 'running' row then outcome row; per-stage tokens, rupees and
  times; the one-pass transcript and outputs; contract checks. Privacy erasure
  empties transcript and outputs (hooked into `finish_erasure`).

A call with segments marked sensitive is skipped (the marks name today's segments
and can't be carried to a new transcript). Our own canary and QA calls are skipped.

## Runner

`python -m ac_platform.one_pass.runner` (host wrapper `ac-one-pass development-live`,
unit `ac-one-pass@.service`): one per database, every 10 s, only transcripts saved
after its first start and in the last two hours, at most two attempts per
transcript, key only in the `infisical run` child.

## Comparison (Admin → One-pass trial)

Per call: cost, tokens and time per stage; transcripts; facts matched by type and
wording; the 27 pointers; the eight dimensions; strengths, improvements and missed
opportunities; which of the six contracts passed. Across calls: ₹ per audio minute
(as run, standard, Flex), median time, agreement, contract pass rate, and the
judges' fact recall and coaching coverage where the research has them. Real calls
and the fictional benchmark set are summarised apart.

## The fictional benchmark set

`--bench <research folder>` runs the 16 fictional calls (never a real call) and
imports the research's own run of today's pipeline on each call's script as the
classic side (Scribe priced at list price). While the bench project's Gemini key is
refused, requests go to Google AI Studio through OpenRouter on the research's
account, data collection denied, each written to the research ledger.

## First measurement: the fictional set (21 Oct 2026)

All 16 fictional calls (264 audio minutes), `both` on dev-live. One pass read each call's phone-quality MP3
through Google AI Studio by OpenRouter. Classic is the research's run of today's pipeline on each call's script
(a perfect transcript), plus Scribe at list price. Rupees at ₹100 a dollar, list prices.

| | today's pipeline | one pass |
|---|---|---|
| ₹ per audio minute, all 16 calls (standard) | 1.00 | 0.50 |
| the same on Flex | (not measured) | 0.25 |
| cost per call (fit) | ₹6.35 + ₹0.61 a minute | ₹5.55 + ₹0.16 a minute |
| a 13.8-minute call, per minute | ₹1.07 | ₹0.57 standard, ₹0.28 Flex |
| fact recall (Haiku judge) | 71.3% | 77.3% |
| unsupported facts | 0.3% | 2.4% (from the transcriber, per the research) |
| coaching truths covered, the 9 calls whose report validated | 68.1% | 71.9% |
| median time per call | 129 s (stages one after another) | 100 s |
| contracts passed | | 89 of 96 |

- The fixed part of one pass is its output (about 12,700 tokens a call: the 27 pointers with their text, the
  detailed C5 overview, the call data) and about 12,000 tokens of instructions. Flex halves it; trimming the
  pointer text is the next lever; the instructions are a shared prefix the implicit cache can reuse at volume.
- The 7 failed contracts were all the C5 detailed overview: that route can't take the strict schema, so JSON mode
  was used. Those reports now stand without the overview (`ok_without_overview`). The direct Gemini route sends
  the strict schema the C5 stage already uses.
- Gemini 3.1 Flash-Lite cut four long calls (22–46 min) short or broke their JSON once; each passed on a retry.
- Spend: about $1.84 of the research's OpenRouter credit, logged in its ledger (`devlive:onepass:*`, judges
  `judge:*`).
