# Call testing after every Play release: plan (13 Nov 2026)

The owner, 13 Nov 2026: "We are calling from the app. The call is picked by some good setup. That setup is
also talking from the perspective of different types: owner, buyer, seller… sometimes the call is not even
sales. How is that detected, how is it analysed by our servers, how can it be improved?" and "After each new
release on Play Store… really test being called… see that the report is being generated."

## What already exists (reused, not rebuilt)

| Piece | What it proves | Gap for this job |
|---|---|---|
| Simulation lab, `scripts/simulation/` (1 Nov) | 31 scripted calls with answer keys; offline two-voice audio (piper); a fake phone through the app's capture API; a grader. Dev only, sandbox organisations | Never goes through the real phone, the real app or production |
| Phone capture proof, 2–3 Nov (staging app, Redmi 13) | A file pushed into the dialler's recordings folder is found, uploaded and analysed by the app itself | Done by hand, staging only, no checker |
| Production canary (`canary_cli.py`) | A 44 s fictional clip goes through every analysis stage on each release | Server side only: no phone, no app, one clip, sales only |
| Jio toll-free IVR (1800 889 9999) | A real outgoing call from the Redmi's SIM: dialler, call history, the phone's own recorder | No seller voice; the far side is a menu |

## How production tells a sales call from anything else today

Read-only and logged (`ctp-prod-detect.sql`, counts only), production, last 14 days:

- **43 reports, none carries a call purpose.** The report (C5) and the facts stage (C4) store no sales or
  not-sales verdict. The model for one exists in code (`call_map.py`: `call_purpose` = sales, support,
  onboarding, internal, personal, unclear, and `call_type.py` derives `not_sales` from it), but the live stages
  don't produce it.
- **The only detection is length.** `call_ai/policy.py` holds a call with less than 20 s of talk, or under 8 s
  from the quieter speaker, as `ai_no_conversation`, and anything under 60 s as `ai_short_call`
  (transcript and lead details, no report). Production held 1 call each way in 14 days.
- **So a personal call, an internal call, a support call or a long wrong number over a minute gets a full
  sales coaching report.** The call data engine's outcome list has `no_conversation` but nothing for
  "not a sales call".

The harness measures exactly this on every release (7 of its 15 scenarios aren't sales), so a fix can be
proved. Fixing detection is a separate change (proposed at the end).

## The options, compared

"Our path" counts the steps a real seller's call takes: (1) dial from the app, (2) the phone's call history,
(3) the phone's own recorder, (4) the app's folder scan, (5) upload, (6) analysis, (7) the report in the app.

| Option | Works on our Android phones today? | Realism | Cost per test call | Our path covered |
|---|---|---|---|---|
| **A. Synthetic call pushed into the recordings folder** | Yes: proven on the Redmi 13 (2–3 Nov). Needs the stamp inside work hours, the file's time set, a lead with that number | Scripted two-voice audio (offline TTS), phone-band filtered; any persona, language or non-sales case | Analysis only: about Rs 3–4 for a 2–3 min call; Rs 0.3–0.5 for one held as short | 4, 5, 6, 7 (not 1–3) |
| **B1. Live call to the Jio IVR from the app** | Yes, today | A real call over the carrier, real recorder; only a menu voice, nobody selling | Analysis only (the SIM's plan covers the call) | 1–7, for the "IVR / not sales" case only |
| **B2. Live call to our own number that plays a two-voice call** | Yes, once a number exists. The far side plays a pre-made conversation (seller and buyer voices) when it answers; the phone's recorder captures the downlink, so the seller side needn't speak | The most realistic audio: carrier codec, real recorder, real timing | Plivo: Rs 0.38 a minute inbound + Rs 200 a month for the number; plus analysis. Exotel only if its account (company calling) already exists | 1–7, any scenario |
| B3. Phone to phone (Redmi calls a second phone) | Not now: the only other test phone, the Note 8 Pro, is the owner's design phone. Stock Android can't put audio into a call's uplink without root | Real, but needs a person, a speaker held to the mic, or root | Free | 1–7 |
| B4. Realtime AI voice agent answering | Yes with a provider number (as B2) plus a voice-agent service | Best for "a buyer who reacts", but the seller still can't speak, so it adds little over B2 for a release check | About Rs 8–25 a minute (agent) on top of B2 | 1–7 |
| C. Server-side upload as a test seller | Yes (dev simulation lab; production canary) | Same audio as A | Analysis only | 5 (API), 6; never the app |

## Recommendation

1. **Build A now (phase 1)** as the release check: realistic personas, non-sales cases, the app's real capture
   path, cheap. It runs on the Redmi 13 against the production Play app, on the QA lead only.
2. **Add B1 to the same command now**, as one live call per run (free): it proves dialling, call history and
   the phone's own recorder on the release that just shipped.
3. **B2 next, after the owner's yes:** one Plivo number (Rs 200 a month, Rs 0.38 a minute, KYC by the owner)
   that answers by playing one of our two-voice calls. It makes the whole path live for sales calls too.
   Nothing is signed up or paid until the owner says yes.
4. B3, B4: not now. C stays as the dev lab for analysis-quality work.

## Phase 1: what gets built (`scripts/call_testing/`)

- **Scenario library** (`scenarios.py`): 15 fictional calls with expectations.
  - **Sales (8):** builder's executive to a first-time buyer; broker to a flat owner (listing mandate);
    broker to an investor (hard price negotiation); builder to an NRI buyer; a cold call turned down; a
    Marathi-English family visit; a Hinglish education counsellor; a closing call where the buyer pays the
    booking amount.
  - **Not sales (7):** a wrong number; a personal call (family); a bank's IVR; an internal call (manager and
    seller); a support complaint from an existing buyer; dead air; a carrier "switched off" message.
  - Each scenario says what must happen: a report, a short-call hold or a no-conversation hold, and whether
    the call is sales.
  - Languages: English, Hinglish, Hindi, Marathi-English. Voices: piper (offline, free), the far side
    phone-band filtered.
  - Scripts are written once and kept fixed, so every release is measured on the same calls. The library
    format is the simulation lab's, so `synth.py` renders them unchanged.
- **Generator** (`generate.py`, on ac): renders the audio once per library version (MP3, like the Xiaomi
  recorder) plus a manifest with each file's length and hash.
- **Runner** (`run.py`, on the laptop with the Redmi on USB):
  - preflight: the phone is ours to drive, the production app is installed and in front;
  - each run makes every file's bytes unique (a run id in an ID3 tag; the audio doesn't change), so the
    server never deduplicates an earlier run;
  - names files like the dialler (`<number>(<number>)_yyyyMMddHHmmss.mp3`) for the QA lead "QA Redmi 10 Nov -
    test", stamps them back to back inside work hours, and sets each file's time;
  - pushes them into the app's recordings folder (`/sdcard/SalesXray-QA-empty`, which holds only test
    recordings), then nudges the app's scan;
  - optional B1: one live call to the Jio IVR with a hang-up scheduled on the phone.
- **Checker** (`check.py`): one read-only, logged query a minute on ac (`costq/q.sh`), matching only our
  files by their SHA-256. For each scenario: uploaded, plan state, held reason, report present, sections
  (summary, strengths, an improvement, 8 dimensions, 9 sections, verdict), a next-call focus (the coaching
  mission), and the call purpose if one is stored. "No crash": the app's process is alive and Android's
  crash log has nothing from it since the run began.
- **Result** (`page.py`): one page, pass or fail per scenario, the time to report, the spend, and a link to
  each report in the app. A JSON file beside it for the next run to compare.
- **Command for the orchestrator after each Play release:**
  `python scripts/call_testing/run.py release --set smoke` (4 calls) or `--set full` (15). Exit code 0 only
  when every scenario passes.

## Isolation and privacy

- Fictional people, companies and numbers; synthetic voices only. No real customer audio is read, copied or
  sent anywhere.
- One QA seller (the Redmi's production sign-in) and one QA lead. Recordings go to the empty QA folder, never
  the phone's real call-recordings folder.
- The checker reads only rows whose source hash is one of this run's files; its output stays on ac; the page
  carries only test data.

## Spend

| Run | Calls | Analysis (production, Gemini) | Seller minutes used |
|---|---|---|---|
| Smoke (every Play release) | 4: two sales reports, one personal call, one dead-air hold | about Rs 8–12 | about 7 |
| Full (weekly, or when analysis changes) | 15 | about Rs 35–45 | about 30 |

Every run logs its spend from the usage export (`/srv/authority-closers/metrics/production/usage.json`).

## Risks

- **Work hours:** the server refuses a call stamped outside them (409, and the app skips it silently). The
  runner stamps inside the last working window and refuses to run when no window fits.
- **Paused capture:** on 10 Nov the Play app paused uploads ("Upload paused · review this call") for a seller
  who skipped the test call. The run reports that as a failure, which is the point.
- **The Redmi is shared** with redmi-fresh-qa: the runner asks for the phone lock through the orchestrator and
  refuses to start while another app (e.g. Sales X-Ray Live) is in front.

## Proposed follow-up (not in phase 1)

Make detection real: have the live facts stage return `call_purpose` (the model already exists), show "Not a
sales call" instead of coaching for personal, internal, support and wrong-number calls, and skip the paid
coaching stage for them. The harness's seven non-sales scenarios are its acceptance test.
