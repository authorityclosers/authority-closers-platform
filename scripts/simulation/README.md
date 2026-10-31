# Simulation lab: synthetic calls and triggers for Sales X-Ray

Owner, 1 Nov 2026: test with the servers and custom software that simulates the real world,
above all **that call reports come out right with both speakers, and that data is extracted
from calls**. No real calls, no real phones, no real people.

Everything here is fictional and runs **on dev only, inside the sandbox organisations**
(AC Sales Sandbox `3100ddbc…`, Fortline Cyber Institute (Sandbox) `37c71e51…`). The tools
refuse any other organisation. They go through the app's own HTTP paths, never the database.

| File | What it does |
|---|---|
| `scenarios.py` | 30 scripted Indian SMB sales calls with answer keys (`build <dir>` writes one JSON each) |
| `synth.py` | Two-speaker audio with offline TTS (piper), plus real-world damage and formats |
| `inject.py` | Puts a call in as a **fake phone** (the Android app's capture API, in its order) or as the **web upload** (/analysis/new), follows it, and saves what the app answered |
| `grade.py` | Scores every call against its key; writes `grades.json` and a Markdown table |
| `triggers.py` | Fires lead bursts, duplicates, call-log bursts, upload failures, a follow-up falling due and a seller stopping new leads, and reads every effect back |
| `probe.py` | Read-only: can these sellers capture and analyse right now (consent, allowance, hours)? |
| `file_bugs.py` | Files misses through the app's own Report a problem, as the sandbox seller |

Tests: `tests/unit/ci/test_simulation_grader.py` (grader maths, the short-call rule, money in
lakh and words, role alignment, the library staying fictional, the Android id scheme).

## The scenario library

Each scenario has: who says what (`S` seller, `P` prospect, `I` IVR), the seller, the path
(phone or web), voices, the answer key in the call data engine's own type keys
(`packages/python/ac_platform/call_data/taxonomy.py`: `person.name`, `company.team_size`,
`money.budget`, `friction.objection`, `commitment.follow_up`, `outcome.call_outcome`, …),
facts that must **not** appear (`forbid`), and the expected stage among the nine sandbox
stages, follow-up time and report outcome.

Coverage: inbound and cold (rejected and positive), heavy objections, a price negotiation
that closes, meetings booked, call-backs, a wrong number, IVR and voicemail, a ~20 s hang-up,
a 45-minute and a 2-hour call (key facts placed at 60-80% of the way in), Hinglish,
Marathi-English and Hindi, a noisy line, a one-side-silent recording, crosstalk, speakerphone
echo, quiet and jumping levels, Xiaomi AMR (8 kHz), MP3, WAV and a stereo M4A.

Lead numbers are `+91 00000 3xxxx` / `4xxxx` (calls), `5xxxx` / `6xxxx` (triggers): no
Indian number starts with 0 after +91, so nothing can ring anyone.

## Running it (on ac only)

Heavy work runs as `acdev` inside `ac-strikes.slice` at nice 15, never on the laptop. The
lab lives in `/home/acdev/simlab` (venv with `piper-tts` and `numpy`, voices in `voices/`,
the AMR codec library unpacked from Ubuntu's `libopencore-amrnb0` into `deb/`; nothing
installed system-wide). Seller passwords come only from Infisical dev `/sandbox-logins`
through `ac-infisical-run`; the tools never print them.

```bash
# 1. Scenarios and audio
simlab .venv/bin/python scripts/simulation/scenarios.py build scenarios
simlab .venv/bin/python scripts/simulation/synth.py scenarios/S01.json out --voices voices \
  --amr-lib deb/root/usr/lib/x86_64-linux-gnu/libopencore-amrnb.so.0
# 2. Can the sellers analyse now?
simlab-probe 3100ddbc-4549-4a5e-85b8-421af6edd588 ac.priya ac.rohan
# 3. Inject, follow and collect
simlab-inject out/S01/truth.json results
# 4. Grade
simlab .venv/bin/python scripts/simulation/grade.py out results --md results/scorecard.md
# 5. Triggers
simlab-triggers 3100ddbc-4549-4a5e-85b8-421af6edd588 ac.rohan results/triggers.json --only burst,dupes
```

`simlab` = `systemd-run --slice=ac-strikes.slice --uid=acdev -p Nice=15 --wait --pipe`;
`simlab-inject` / `-probe` / `-triggers` add `ac-infisical-run` (dev, `/sandbox-logins`) and
`runuser -u acdev`. `simlab-guard` pauses (SIGSTOP) only these scripts while the 1-minute
load is above 6 and resumes them below 4.5.

## What the fake phone does (from `apps/phone/android/.../CaptureUploadWorker.java`)

1. `GET /v1/lead-desk/phone-book`: identity `tenant_id:person_id`, the work hours.
2. `GET /v1/conversation/acquisition/upload-policy` and `GET /v1/sales-xray/call-ai/auto-analysis`
   (standing consent on, terms hash equal).
3. `POST /v1/lead-desk/recording-call` with `X-Auto-Capture-Identity` and `Idempotency-Key`:
   the lead's call, before any audio.
4. `POST /v1/lead-desk/phone-log` with the same call (READ_CALL_LOG builds): it must not add
   a second call.
5. `PUT …/submissions/{sid}/source`, sid = Java `UUID.nameUUIDFromBytes("sx-auto:" + identity + ":" + eventId + ":0")`,
   headers `X-Source-SHA256`, `X-Capture-Source: android_dialer_pickup`, `X-Upload-Policy`,
   `X-Upload-Consent: standing`.
6. `POST /v1/lead-desk/leads/{lead}/recordings` (attach), then the quote and plan if the
   server did not start the analysis itself; poll every 10 s until a report or a hold.

Two server rules shape the phone path: a call must start inside the organisation's work
hours, and after its lead was created. Outside work hours the fake phone dates the call inside
the last working day (a phone that uploads late), and it calls existing sandbox leads (never
used ones first, registry in `results/leads.json`). The server clock is never touched.

## Grading

- **Report:** the short-call rule decides what is expected: under 20 s (or one side under 8 s)
  `ai_no_conversation`, under 60 s `ai_short_call` (transcript and lead details only),
  otherwise a report.
- **Roles:** transcript segments lined up with the truth timeline (or by words), share of
  words given to the right side; unnamed labels take the better of the two assignments.
- **WER:** only when transcript and script share a script (Latin/Devanagari).
- **Facts:** recall over the key's items, precision over extracted objects of graded types
  (plus anything forbidden). Money understands lakh, thousand, k, words and ranges.
- **Stage and follow-up:** the lead's stage after the call against the allowed stages; the
  next meeting or task against the agreed day and hour (India time).
- **Pass:** report as expected; where a report is expected, facts recall ≥ 60% and roles
  ≥ 80%; and the stage allowed.

## Cost

Call analysis spends real AI money (≈ ₹0.27–1.1 per minute of audio). Run five calls first,
measure the cost per minute, and get a go-ahead before the rest. Never raise an AI or
allowance cap from here.
