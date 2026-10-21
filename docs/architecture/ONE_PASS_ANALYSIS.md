# Sales X-Ray one-pass analysis (Google only)

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

Two modes use the Google-only read; both put every request through the AI spend guard
(feature `one_pass`) and record it in `one_pass_runs`.

**`both` (development): the trial, beside today's pipeline.**

```
today's C2 transcript saved ─► admitted (consent, retention, erasure, newest)
   ─► the AI spend guard (feature one_pass) ─► 'running' row committed
   ─► the call's stored audio as mono 32 kbps MP3
   ─► Gemini 3.1 Flash-Lite: speaker-labelled, timed segments ─► C2 contract
   ─► two Gemini 3.8 Flash requests at once, each with a strict schema:
        facts  = call_data + notes + review      report = the C5 report
   ─► each part checked by its own stage's validator ─► outcome row (compared)
```

**`one_pass` (development, staging): people see it.** Today's C2, C4 and C5 stay as they
are (C5 already sends its strict schema to Gemini directly), and so does the fast call
data pipeline. The deep call data read (whole-call facts, then per-segment labels in
several more requests) and the AI pointer review become one strict Gemini 3.8 Flash
request on the same saved transcript (`publish.py`):

```
fast call data finished on the newest C2 transcript ─► admitted ─► spend guard
   ─► 'running' row ─► one strict request: call_data (every type) + review (in full)
   ─► call data: the call's deep run and objects, through the deep pipeline's own merge
      (created_by automatic:one-pass, with its audio measurements, no tokens or rupees)
   ─► when the call's report is saved: the review, parsed against the report's own
      transcript and withheld segments, saved through save_review (same admission)
```

Fallback: whatever one pass does not finish (failed, refused, skipped, nothing valid, a
review not published within an hour) goes to today's deep pipeline and pointer review.
They wait (`Handoff`) only while one pass works on the call, or for at most 15 minutes
after the transcript while it has not started. Switching to `classic` ends every wait.

1. **Transcription** (`transcription.py`, trial only). The research's prompt and schema.
   Times (MM:SS) are normalised: ordered, at least 300 ms, inside the call. Speakers
   become `speaker_0`, `speaker_1` in order of first speech. The result is today's C2
   shape and passes the Report's own transcript validator.
2. **Analysis** (`analysis.py`). The instructions are the product's own: the C5
   coaching-v5 prompt as the C5 stage builds it, the call data extraction's instructions
   and the pointer review's. The Gemini API refuses one strict schema for all four parts
   ("invalid argument", 21 Oct 2026), so the parts go as two requests at once, each with
   its strict schema; publishing never falls back to sending a schema as text.

   | part | request | checked by | becomes |
   |---|---|---|---|
   | `call_data` (every model type) | facts | `call_data.extraction` | call objects, prospect facts |
   | `notes` (trial) | facts | `reports.parse_fact_packet` | C4 facts, with the call objects |
   | `review` | facts | `pointer_review.parse_review` | the pointer review |
   | `report` (trial) | report | `reports.parse_report_draft` (coaching-v5) | the C5 report and coaching |

   Lean output: per-segment labels are not asked for; in the trial the prospect
   profile's facts come from the call data facts. The instructions come first and are
   the same for every call, so Gemini's implicit cache can reuse that prefix. Every
   request asks for compact JSON, and the trial's pointer text and report have word
   limits (see "Output trim" below).
3. **Tiers.** Standard or Flex per stage (Admin). Flex is half price, best effort, may
   queue for minutes; after three busy answers a request falls back to standard once,
   and the run records `flex_fell_back`. Staging and production: standard only for now.

## The switch (Admin → One pass, and All settings)

| mode | what happens | where |
|---|---|---|
| `classic` | today's pipeline only. The default everywhere; one click back | everywhere |
| `both` | today's pipeline, and the Google-only read beside it; people see today's | development |
| `one_pass` | deep call data and pointer review from one read; people see it | development, staging |

`one_pass` is the owner's action (owner, 21 Oct 2026: "So at least get this on prod
now!!!"): a control account signed in within ten minutes types `one_pass`, gives the
reason in the owner's words, and the environment's one-pass spend cap must be above ₹0
with background AI on. It is audited as `analysis_pipeline.one_pass_switched_on`.

**Production** runs no call data engine (only C2 Scribe, C4, C5 and the pointer review),
so this read would replace only the pointer review there. Production's one-pass saving
is its transcription: Gemini 3.1 Flash-Lite as the sealed C2 route (≈ ₹0.78 → ≈ ₹0.64 a
minute for a 14-minute call at list price), chosen through Providers and the hosted
approval bundle; see `docs/ops/ONE-PASS-PRODUCTION.md`.

## Money

Every request goes through the AI spend guard as feature `one_pass`. Its cap starts
at ₹0 in every environment; raising it in Admin → AI spend is the recorded approval.
Development's background AI must also be on. The ledger reads `one_pass_runs`: one
line per stage (Flash-Lite with its audio minutes, the 3.8 Flash requests together), a
start without an outcome counts ₹2. A published read's deep run and review carry no
tokens or rupees, so nothing is counted twice. Rupees are list prices (`pricing.py`,
read 20 Oct 2026; 3.8 Flash doubles on 1 Jan 2027), Admin only, never on a user screen.

## Data

Migration `20261021_0116` (backup parity v83), both append-only:

- `analysis_pipeline_settings`: revisions of the switch, audited with the reason.
- `one_pass_runs`: 'running' row then outcome row; per-stage tokens, rupees and
  times; the one-pass transcript and outputs; contract checks. Privacy erasure
  empties transcript and outputs (hooked into `finish_erasure`).

A trial call with segments marked sensitive is skipped (the marks name today's segments
and can't be carried to a new transcript); a published read leaves withheld segments
out. Our own QA calls are skipped; the release canary's own call is read in `one_pass`
mode, so each release exercises it.

## Runner

`python -m ac_platform.one_pass.runner` (host wrapper `ac-one-pass development-live |
staging | production`, unit `ac-one-pass@.service`; inside the worker container on
staging and production, as the call data engine): one per database, every 10 s, only
transcripts saved after its first start and in the last two hours, key only in the
`infisical run` child. Trial: at most two attempts per transcript; publishing: one.

## Comparison (Admin → One pass)

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

## Output trim (21 Oct 2026, `one-pass-analysis/3`)

Output is most of the analysis cost: Gemini 3.8 Flash charges $3.75 per million output tokens and $0.75 per
million input tokens. The trim was measured on 6 fictional calls (fx-04, 07, 11, 12, 13, 14; 69 audio minutes),
reading each call's stored 21 Oct Flash-Lite transcript. Requests went to Google AI Studio through OpenRouter with
strict schemas, priced at the standard list price with that call's own transcription cost added. Judges were the
research's Haiku judges on the Claude subscription. Spend was $0.75 of the orchestrator's $1.20, logged in the
research ledger as `devlive:onepass-trim:*`. Results: `results/onepass-trim/` in the research folder.

**Where the tokens went** (the previous prompt, two strict requests):
- The facts request wrote about 7.7k tokens a call and the report about 2.9k.
- Gemini indents its JSON unless told otherwise. It did so on every facts answer (370–890 lines) and on 2 of the 6
  reports. That indentation was about a third of the facts request's output tokens.
- In the content itself, the 27 pointers take about two thirds of the review (what happened 15 words on average,
  why it matters 10). JSON keys are 25–45% of each part's characters.

**What changed:**
- **Every one-pass request** (the trial, publishing and the plan's C4 request) asks for compact JSON on one line.
  This changes no content.
- **The trial's review** keeps the pointer review's own instructions, with lower limits:
  - what happened in at most 12 words, and why it matters in at most 10;
  - tips at most 10 words each, and none for an excellent pointer;
  - reasons, objections, next steps and insights get word limits too.
- **Call data and notes** are told the limits never apply to them. A first version without this lost 27% of the
  notes text, and fact recall fell to 71%.
- **Training topic:** the trial no longer asks for it. Each pointer's own label fills it, and the Report shows it
  as the training name.
- **The trial's report** keeps the coaching-v5 instructions whole and adds word limits after them. Coaching-v5 sets
  no lower bound.
- **Publishing and the plan's C4 request** keep the review's own text. The B3 calibration was fitted on that text.

| 6 fictional calls | previous prompt | trimmed |
|---|---|---|
| output tokens a call (facts + report) | 10,578 (7,708 + 2,870) | 6,272 (4,589 + 1,683) |
| ₹ per audio minute, all 6 (standard) | 0.566 | 0.428 |
| a 13.8-minute call, fit over the 6 (standard / Flex) | ₹0.50 / ₹0.25 | ₹0.39 / ₹0.19 |
| fx-13 alone (14.1 min, dense) | ₹0.541 | ₹0.438 |
| contracts passed | 36 of 36 | 36 of 36 |
| fact recall (Haiku judge) | 76.9% | 76.4% |
| coaching truths covered (pooled) | 17.5 of 23 | 18 of 23 |
| unsupported facts a call | 1.5 | 2.7 |
| call objects; C4 observations | 165; 236 | 180; 250 |
| pointer status the same as the other prompt's read | 75% (two reads of one prompt: about 80%) | |
| C5 dimension status the same | 98% | |
| mean overall score, trimmed minus previous | −0.2 points | |

- **Where the saving came from:** about 70% of it is the indentation. The rest is shorter text, mostly in the
  report, whose content fell by about a quarter.
- **The target is met on the fit, not on every call.** The ₹0.39 comes from a straight line through 6 calls. The
  one dense 14-minute call measured ₹0.44.
- **Transcription is now the largest single cost,** about ₹0.13–0.16 a minute (40% of the total).
- **Implicit caching is not counted.** Every bench request read 0 cached tokens. In steady traffic, the roughly
  10k shared instruction tokens of the two requests could save about ₹0.05 a minute.
- **Noise:** a single read of a call's coaching is noisy, because each call has only 2–6 coaching truths.
- **Check judge files for errors before comparing.** One judge answer was unreadable JSON and scored a call 0 of 4
  until it was re-judged.
