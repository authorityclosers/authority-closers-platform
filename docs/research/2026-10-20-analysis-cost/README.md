# Analysis cost research, 20–21 Oct 2026

How to cut Sales X-Ray's call-analysis cost from ≈ ₹1.19 per audio minute (13.8-minute call, staging receipts) to
≤ ₹0.40, then ≤ ₹0.10, without losing quality. Research only: nothing here changes a production pipeline or official
scoring.

- **Paper (private Artifact):** https://claude.ai/artifact/4Ykok16hhzHu2pyfBetmV7, built from `paper/site/`.
  The sections in `paper/0*.md` are its source text.
- **Answer, in short (v2.0, after 7 real calls annotated by the coaching lead):** transcribe with Gemini 3.1
  Flash-Lite, measure pauses locally, and run ONE analysis pass with the coaching lead's Brain 4.0 rubric (facts,
  18 scores, timestamped coach notes, report).
  1. **Lean (recommended):** GPT-6 Luna for the pass. ₹0.29 a minute standard, ₹0.15 on Flex/batch (today ₹1.50 on
     the real calls, ₹1.19 on staging). Most facts (90.5% on the fictional set, today 68.4% on the same transcripts),
     coaching about 5 points behind today on the coaching lead's notes (−5.2 [−10.8, +1.1]).
  2. **Best coaching:** Gemini 3.8 Flash on the same prompt. 50.0% of the coaching lead's notes against 46.0% for
     today (+4.0 [−1.8, +10.5]); ₹0.50 standard, ₹0.25 Flex; doubles on 1 Jan 2027.
  3. **Both in parallel:** Luna's facts and scores plus Gemini's coach notes, ₹0.54 / ₹0.27.
  - One pass loses nothing against today's six stages on the same transcript (fictional and real). Delivery must be
    measured from the audio, not heard by a model. Premium models (Sonnet 5.5, GPT-6.1 Sol) were not better.
  - Before production: approval of the data flows (AC-GOV-AUD-001), a staging shadow week, AC-SVAL before any Brain
    4.0 score is official. Scribe was never measured (no bench key).
- **The ₹0.10 configuration (round 8, `paper/11-full-formats.md`):** Flash-Lite on Gemini Flex + GPT-6 Luna on
  OpenAI Flex answering the one-pass build's own two requests in the product's full formats (C4, C5 coaching-v5,
  pointer review, call data): ₹0.108/min at 13.8 min, ₹0.083 at 60, ₹0.18 at 4.5 (fictional calls). All C5
  reports and pointer reviews valid with the report-depth prompt. Facts above today's; coaching within noise (−2.5).
  A Gemini report on Luna's facts: +4.2 coaching, ₹0.155 on Flex. Real calls ≈ ₹0.15 until the transcript output
  is compact. Judged on the Claude subscription (`claude-sub/haiku`); that judge varies ±8 points on facts.
- **Reviews:** Codex (GPT-6.1 Sol) *disagree*, Gemini 3.8 Flash (agy) *agree with changes* on v1.0; see
  `paper/09-review.md`. The real-call rounds (section 10) came after the reviews.

## Contents

| Path | What |
|---|---|
| `paper/0*.md`, `paper/10-real-calls.md`, `paper/11-full-formats.md` | sections: cost anatomy, market, benchmark design, pipeline shapes, method, results, recommendation, next steps, cross-review, real calls and Brain 4.0 |
| `brain4/` | full-text digests of the coaching lead's "Accuracy Brain 4.0" rubric (dimensions 1–10 and 11–18); the compact prompt is `harness/brain4_rubric.txt` |
| `results/realcalls/` | real-call scores (ids rc-01…07 only), the paired bootstrap and durations; audio, transcripts, notes and names stay on ac |
| `paper/costmodel.py`, `paper/scenarios.json` | the cost model (fixed per call + per minute) and its scenarios |
| `paper/site/` | the published page: `index.html` template, `build.py`, `data/*.json`, and the built `sales-xray-analysis-cost.html` |
| `dataset/calls/fx-*/` | 16 fictional calls: `plan.json` (speakers, coaching truths), `script.json`, `facts.json` (ground truth), `ideal_report.json` (product v4 schema) |
| `bench/` | call checker, script brief, TTS renderer, round-trip check, self-hosted ASR, FLEURS builder, distillation experiment, and reference copies of the GitHub workflows used on `bench*/**` refs (`workflows/*.yml.txt`, not active) |
| `harness/` | benchmark driver: `run.py` (asr / text / audio1 / judge / rjudge / retain), `today.py` (today's pipeline from the product's own prompt builders), `shapes.py`, `score.py`, `summary.py`, `fits.py`, `boot.py` (paired bootstrap) |
| `results/scores/` | score tables (`*.md`, `*.json`): ASR, retention, facts, report, consistency, cost, leaderboard, fits, bootstrap |
| `results/reviews/` | the review brief and the two independent reviews |
| `results/distil/` | the segment-label distillation results |
| `results/spend.md` | requests and dollars per provider, from the request ledger |

## Rules that held

- Fictional calls and public CC-BY speech (Google FLEURS) went to new providers. The seven real calls went to
  Google, OpenAI (Azure), Anthropic and OpenRouter only after the owner approved it on 21 Oct. No production row was
  read.
- Budget: $20 OpenRouter credit, raised by the owner to $30 (see `results/spend.md`) plus free credits (Deepgram, AssemblyAI,
  Sarvam, Groq) and GitHub's free runners. Keys lived in Infisical (dev, `/sales-xray-bench`) and were injected by
  `ac-infisical-run`; none is in these files. The request ledger (`results/ledger.jsonl` on ac) holds tokens, audio
  seconds and cost, never content.
- Customer and staff names do not appear; all names in the dataset are invented.

## Reproduce

On ac, with keys injected:
`sudo -n env AC_INFISICAL_ENVIRONMENT=dev AC_INFISICAL_PATH=/sales-xray-bench /usr/local/sbin/ac-infisical-run --
setpriv --reuid=acdev --regid=acdev --init-groups -- <script>`. Harness entry points are `harness/round1.sh <step>` and
`python run.py ...` with `PYTHONPATH=<workbench>/packages/python:.`, run under `nice -n 19 ionice -c3`.

Audio (≈ 500 MB as FLAC + MP3) is not in git. It is rendered deterministically on GitHub's free runners by
`bench/render_call.py` (workflow `bench/workflows/bench-tts.yml.txt`, Kokoro voices + espeak G2P, phone simulation)
and fetched with `bench/fetch_audio.sh`. A copy lives on ac under `/home/acdev/research/analysis-cost-20261020/bench/audio`.
