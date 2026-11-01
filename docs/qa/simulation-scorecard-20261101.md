# Simulation scorecard, 1 Nov 2026 (dev, sandbox organisations)

Owner order, 1 Nov 2026: simulate the real world with custom tools, above all **proper report
generation and data extraction from calls**. Tools: `scripts/simulation/` (README there),
committed on the workbench as `d8d0361f3`; wb-ci run 41252882666 green (lint and 25 grader tests).

Everything below ran on **dev**, inside **AC Sales Sandbox** (`3100ddbc…`) and **Fortline Cyber
Institute (Sandbox)** (`37c71e51…`), as fictional sellers, through the app's own HTTP paths. No
real numbers (`+91 00000 xxxxx`), no production, no phones.

## Headline

| Area | Result |
|---|---|
| Part 1: report and data extraction | **Blocked**: every sandbox seller has a call allowance of 0 seconds, so every upload is refused (409) before analysis. Nothing could be graded. Filed `5605dd37`. |
| Fake phone, up to the upload | **Pass**: the lead's call is created, and the call-log sync of the same call is recognised (`already=1`, same event); a retried call returns the same event |
| Upload refusals | **Pass**: stale terms 422, no consent 422, another seller's identity 409, a call 2 h in the future or 5 days old 422 |
| Lead burst (100 in 60 s) | **Pass** with one slow request: 100/100 created, median 100 ms, p95 600 ms, max 13.4 s |
| Duplicates | **Pass**: adding the seller's own number again (4 spellings) hands back the existing lead; no duplicate. (`d208a435` was filed in error and withdrawn by `3f995945`.) |
| Call-log burst | **Pass**: 59/60 logged, the repeat logs nothing new, 201 rows refused (422) |
| Follow-up falling due | **Pass**: the call-back moved into Leads "Late" and "Due today" (the badge counts only follow-ups over an hour late; Follow-ups → Overdue means planned before today). `67e0ed7e` was filed in error and withdrawn by `0ff39cb4`. |
| Public intake refusals | **Pass**: 12 of 12 refused, no lead created |
| Seller stops taking leads | **Not tested properly**: needs leads from a source (admin-only) |
| Meta/Google webhooks with real payloads, website leads, 5,000-row import, a seller removed mid-day | **Blocked**: need an organisation admin in the sandbox (only the owner's and Dipak's real accounts are admins) |

AI money spent: **₹0** (no analysis could start).

## Part 1: the 30 synthetic calls

Audio: offline TTS (piper, English/Hindi/Marathi voices), the far side band-limited like a phone
line, at ~130-150 words a minute. Answer keys are in the call data engine's own type keys. The
grader decides from the short-call rule what each call should get (report, `ai_short_call`
transcript and lead details, or `ai_no_conversation`).

| Id | Call | Language | Path | Audio | Length | Expected from the app | Key items | Stage after | Status |
|---|---|---|---|---|---|---|---|---|---|
| S01 | Inbound enquiry from a Meta form, demo booked | english | phone | M4A | 175 s | full report | 13 | meeting_scheduled | blocked |
| S02 | Cold call, rejected: in-house trainer already | english | phone | MP3 | 87 s | full report | 6 | lost | blocked |
| S03 | Inbound, heavy objections, follow-up agreed | english | phone | M4A | 148 s | full report | 13 | interested | blocked |
| S04 | Price negotiation on the team package, closed at 1.55 lakh | english | phone | M4A | 124 s | full report | 9 | won | blocked |
| S05 | Busy prospect asks for a call back tomorrow at 6 pm | english | phone | M4A | 53 s | transcript + lead details (ai_short_call) | 6 | open_leads | blocked |
| S06 | Wrong number | english | phone | AMR | 24 s | no report: ai_no_conversation | 1 | junk | blocked |
| S07 | Switched-off IVR, then voicemail beep | english | phone | M4A | 24 s | no report: ai_no_conversation | 1 | not_connected | blocked |
| S08 | Hang-up after about 20 seconds | english | phone | M4A | 21 s | no report: ai_no_conversation | 1 | not_connected | blocked |
| S09 | 45-minute discovery call, proposal meeting booked | english | phone | M4A | 45.6 min | full report | 11 | meeting_scheduled | blocked |
| S10 | 2-hour workshop call, visit booked | english | phone | M4A | 117.9 min | full report | 10 | meeting_scheduled | blocked |
| S10X | 2 h 06 min call: over the pipeline's 2-hour limit | english | phone | M4A | 126.3 min | refusal before spend (over 2 h), or a report | 10 | – | blocked |
| S11 | Hinglish inbound enquiry, visit booked (web upload) | hinglish | web | M4A | 106 s | full report | 10 | meeting_scheduled | blocked |
| S12 | Marathi-English call, follow-up next Monday | marathi-english | phone | M4A | 87 s | full report | 11 | interested | blocked |
| S13 | Hindi call with objections, brochure on WhatsApp (web upload) | hindi | web | M4A | 100 s | full report | 10 | interested | blocked |
| S14 | Noisy line (market noise), demo booked | english | phone | M4A (noise) | 78 s | full report | 10 | meeting_scheduled | blocked |
| S15 | One-side-silent recording (prospect not recorded) | english | phone | M4A (silent side) | 64 s | hold (one side silent) or report | 2 | – | blocked |
| S16 | Crosstalk: both speak over each other during the price talk | english | phone | M4A (crosstalk) | 101 s | full report | 7 | interested | blocked |
| S17 | Speakerphone with echo, call-back on Saturday | english | phone | M4A (echo) | 77 s | full report | 8 | open_leads | blocked |
| S18 | Fortline inbound: working professional, counselling session booked | english | phone | M4A | 78 s | full report | 10 | meeting_scheduled | blocked |
| S19 | Fortline cold call to a company: phishing workshop proposal | english | phone | MP3 | 78 s | full report | 12 | interested | blocked |
| S20 | Fortline Hinglish fee negotiation, enrolled with EMI (web upload) | hinglish | web | M4A | 91 s | full report | 8 | won | blocked |
| S21 | Fortline: student asks to be called after exams | english | phone | M4A | 44 s | transcript + lead details (ai_short_call) | 6 | open_leads | blocked |
| S22 | Fortline: lost, prefers free YouTube courses | english | phone | M4A | 44 s | transcript + lead details (ai_short_call) | 5 | lost | blocked |
| S23 | Meta lead turns out to be a job seeker | english | phone | M4A | 46 s | transcript + lead details (ai_short_call) | 3 | junk | blocked |
| S24 | After the demo: meeting done, waiting on the brother | english | phone | M4A | 83 s | full report | 9 | meeting_done | blocked |
| S25 | Very quiet prospect, level jumps (web upload) | english | web | WAV (levels) | 77 s | full report | 9 | won | blocked |
| S26 | Xiaomi recorder AMR (8 kHz narrowband) | english | phone | AMR | 75 s | full report | 11 | interested | blocked |
| S27 | Stereo recording (seller left, prospect right) | english | phone | M4A stereo | 77 s | full report | 10 | interested | blocked |
| S28 | Marathi-English cold call, meeting booked | marathi-english | phone | AMR | 85 s | full report | 8 | meeting_scheduled | blocked |
| S29 | Hindi call: parent asks about the course for his son | hindi | phone | M4A | 80 s | full report | 8 | interested | blocked |
| S30 | Lost: already signed with another training firm | english | phone | M4A | 44 s | transcript + lead details (ai_short_call) | 6 | lost | blocked |

**Status of every scenario: blocked at the upload** (409 "Your current free call allowance has
been used.", allowance_seconds 0 for all 10 sandbox sellers). S01 went through the phone path up
to that point: `recording-call` 200 on an existing lead (Nilesh Reddy, stage new), the phone-log
of the same call `already=1` with the same event id, then the upload refused.

What runs the moment minutes exist (no code change):

```bash
simlab-inject out/S01/truth.json results        # one call; then S02..S05, measure ₹/min
simlab .venv/bin/python scripts/simulation/grade.py out results --md results/scorecard.md
```

## Part 2: triggers (seller Rohan, AC Sales Sandbox)

| Trigger | What was sent | What came back | Result |
|---|---|---|---|
| Burst | 100 `POST /leads` (assign "rules") paced over 60 s | 100 × 201; p50 100 ms, p95 600 ms, max 13.4 s; all 100 owned by Rohan (a seller's own adds stay with them); alert "101 leads to call now"; Leads "created today" 0 → 100 | Pass (one 13 s request) |
| Duplicates | Rohan's lead `+91 00000 50900`, then the same number as `+91 00000 50900`, `+910000050900`, `910000050900`, `+91-00000-50900` | All 201, each handing back the existing lead (listing shows only the original); `/leads/match` says found, yours. `0 00000 50900` became `+000050900` (read as international: an artefact of the fake numbering, not a real-world case) | Pass |
| Call-log burst | `phone-log` with 60 calls on Rohan's older leads, dated inside Saturday's hours (outgoing, missed, incoming, rejected; 0-300 s), sent twice, then 201 rows | First: logged 59, skipped 1 (852 ms). Repeat: logged 0, already 59 (122 ms). 201 rows: 422 (the error echoes the whole request, numbers included) | Pass |
| Upload failures | Stale terms hash, no consent header, another seller's identity, wrong checksum, non-audio body, valid web and standing uploads | 422, 422, 409 "belongs to another workspace or seller"; the rest 409 allowance (the allowance check comes before the bytes, so checksum and non-audio could not be reached) | Pass where testable |
| recording-call | Same command twice; a call 2 h ahead; a call 5 days old | Same event both times; 422; 422 | Pass |
| Follow-up due | A call-back task due 2 min after creation on a new lead | After it fell due: in Leads "Late" (11) and "Due today"; not in Follow-ups → Overdue (9, planned before today) nor the badge (1, over an hour late), both by definition. Call-backs are not on the Tasks list (calling kinds, by design); Soon is quiet outside work hours (by design) | Pass |
| Seller leaving | Rohan turns new leads off, adds 10 leads, turns them on | 10 × 201, all Rohan's: a seller's own adds are theirs. Routing away from a seller who stopped needs leads from a source | Not tested |
| Intake refusals | Website line with no key, an unknown key, another page, no page; hello with an unknown key; Google Ads with no key and an unknown source; capture with no key and an unknown key; Meta verify with a wrong token, posts without and with a bad signature | 401, 401, 403, 422, 401, 422, 401, 401, 401, 403, 401, 401; leads created today 114 → 114 | Pass (12/12) |

## Rules of the app that shaped the lab

- A phone's call is refused outside the organisation's work hours (sandbox: Mon-Sat 10:30-19:00
  India time; this ran on Sunday). The fake phone dates calls inside the last working day, as a
  phone uploading late would; the server clock was never touched.
- A recording's call must start after its lead was created, so the lab calls existing sandbox
  leads (never-used ones first) instead of new ones.
- The analysis pipeline caps a call at 7,200 s (2 hours) in several places. S10 is 117.9 min,
  inside it; S10X (the first 2 h 06 min render) is kept to test what an over-limit call gets.
- The short-call rule: under 60 s of transcript a call gets its transcript and lead details only,
  under 20 s (or under 8 s from the quieter side) no conversation. Calls meant to get a report
  run 75 s or more; S05, S21-S23 and S30 sit under a minute on purpose.

## Bugs filed (Report a problem, as the sandbox seller)

| Id | Builder | Severity | What |
|---|---|---|---|
| `5605dd37` | capture-setup (call analysis / billing for the words) | high, blocks work | 0 call minutes in both sandboxes; the upload says the allowance "has been used"; a phone would hold every call silently |
| ~~`d208a435`~~ | Leads | — | Filed in error (a 201 that returns the existing lead was read as a new one); withdrawn by `3f995945` |
| ~~`67e0ed7e`~~ | Leads | — | Filed in error (three late counts that differ by definition); withdrawn by `0ff39cb4` |

## Left in the sandbox (fictional, for clean-up with the owner's "approve delete")

AC Sales Sandbox: 100 "SIM Burst 10312302 NNN" and 10 "SIM Burst 10312311 6NN" leads, 3 "SIM Dupe"
leads, 1 "SIM Due" lead with 2 call-back tasks (all `+91 00000 5xxxx`), the lead "Anil Deshmukh"
(`+91 00000 30001`), 59 phone-logged calls on Rohan's older leads (Saturday), and one Saturday call
without a recording on Nilesh Reddy.
