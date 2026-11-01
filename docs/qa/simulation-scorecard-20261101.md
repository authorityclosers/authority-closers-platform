# Simulation scorecard, 1 Nov 2026 (dev, sandbox organisations)

Owner order, 1 Nov 2026: simulate the real world with custom tools, above all **proper report
generation and data extraction from calls**. Tools: `scripts/simulation/` (README there),
committed on the workbench (first `d8d0361f3`, wb-ci 41252882666; this run's grader and fake-phone
changes with this scorecard).

Everything below ran on **dev**, inside **AC Sales Sandbox** (`3100ddbc…`) and **Fortline Cyber
Institute (Sandbox)** (`37c71e51…`), as fictional sellers, through the app's own HTTP paths. No
real numbers (`+91 00000 xxxxx`), no production, no phones.

Call minutes: the owner approved 300 minutes (1 Nov, orchestrator chat). They were granted to the
fictional seller **ac.priya** (AC Sales Sandbox) through the audited admin route
(`POST /v1/admin/conversation-minute-accounts/…/grants`, grant `ffda1fdd`, logged in
`/var/log/ac-owner-data-changes.log` at 04:06:18Z), so every call ran as Priya.

## Headline

| Area | Result |
|---|---|
| Part 1: 31 synthetic calls | **29 pass, 2 fail.** 21 full reports, 8 short calls held as designed, 2 long calls refused at upload |
| Speaker roles | **20 of 21** report calls 100% right; S20 (Hindi web upload) has the two sides swapped. The app left the roles undecided on 4 calls (S24, S25, S27, S28) |
| Word error rate | English **2.6%** mean, 2.3% median, worst 5.7% (14 calls; S15 is 50% because its prospect was not recorded). Hindi 23%, Hinglish 37%, Marathi-English 27% (code-mixed: an upper bound, see below) |
| Facts, recall | **87%** of the answer keys' items (165 of 189) are in the reports' own words; worst call 67%. Misses: the city (11) and the company name (6) |
| Facts, precision | Rupee figures: **46 of 51** match the call. Of the 5 others, 4 are worked out from it (10 × ₹45,000; a ₹35,000 discount; an EMI of about ₹8,500; a ₹10,000 concession) and **1 is wrong** (S15, misheard) |
| Next step | The follow-up day and time are right in **16 of 16** reports that name one |
| Stage | Round one: guarded (dev’s AI spend guard skips sandbox organisations). **Round two, engine on (10 calls):** no stage moved without a tap; the stage offered was right in 7 of 10; a closed deal and a booked meeting got no offer, because the outcome is never read (`8d68f322`) |
| Latency | Upload accepted → report: median **62 s**, p90 93 s, worst 237 s (the 45.6-minute call). Short-call holds 21–23 s |
| Where calls land | All **25 of 25** phone uploads sit once on their lead with the recording; the call-log sync of the same call is recognised (`already=1`). The Calls tab counts 29 (21 completed; the 8 held short calls are in no bucket) |
| Long calls | **Fail**: 117.9 min refused "longer than 60 minutes … Split it and try again" (owner order: 120 min everywhere); 126.3 min refused before spend but with "The audio length could not be verified" |
| AI spend | Round one **₹71.12** for 81.6 analysed minutes (29 calls) = **₹0.87/min**; nothing for the 2 refused calls. Round two ₹56.47 (analyses ₹44.78 with the engine’s ₹7.41, one-pass trial ₹11.69). The fix's re-check ₹1.19. **Day: ₹128.78** of the approved ₹280 |
| Call data engine (round two) | Structured facts recall 88%, precision 94%; lead fills 5 right, 1 wrong; follow-up dates right in 4 of 6 (“tomorrow” counted from the analysis day, `deb67f5f`) |
| Part 2: triggers | Unchanged from the first pass below (all testable triggers pass) |

## Part 1: the 31 synthetic calls

Audio: offline TTS (piper, English/Hindi/Marathi voices), the far side band-limited like a phone
line. Answer keys are in the call data engine's own type keys. The grader decides from the
short-call rule what each call should get. Calls ran on Sunday, so the fake phone dated them back
to back inside Saturday's work hours (10:50–17:45 India time); 25 went through the Android capture
path, 4 through the web upload (`/analysis/new`).

**How it was graded on dev.** The call data engine (structured facts, lead fills, stage
suggestions) is a background AI job, and dev's AI spend guard keeps background AI off and skips
sandbox organisations (`ai_spend/guard.py`, owner 20 Oct 2026); the lab did not raise it. So the
report is the only extraction: **Facts R** is the share of the key found in the report's own words
(the transcript quotes it cites are left out), **P** is the share of the report's rupee figures the
call really said, stage is marked *guarded*, and the follow-up is read from the report's next step.

| Scenario | Path | Length | Result | Report (want/got/hold) | Roles | WER | Facts R/P | Stage before→after (want) | Follow-up | Latency |
|---|---|---|---|---|---|---|---|---|---|---|
| S01 Inbound enquiry from a Meta form, demo booked | phone | 175 s | **pass** | True/True/– | 100% | 1% | 85% / 100% | new→new (meeting_scheduled) guarded | ok | 69 s |
| S02 Cold call, rejected: in-house trainer already | phone | 87 s | **pass** | True/True/– | 100% | 2% | 100% / – | new→new (lost) guarded | – | 63 s |
| S03 Inbound, heavy objections, follow-up agreed | phone | 148 s | **pass** | True/True/– | 100% | 2% | 80% / 100% | new→new (interested) guarded | ok | 62 s |
| S04 Price negotiation on the team package, closed at 1.55 lakh | phone | 124 s | **pass** | True/True/– | 100% | 5% | 89% / 100% | interested→interested (won) guarded | – | 64 s |
| S05 Busy prospect asks for a call back tomorrow at 6 pm | phone | 53 s | **pass** | None/False/ai_short_call | – | no transcript | 0% / – | new→new (open_leads) guarded | – | 23 s |
| S06 Wrong number | phone | 24 s | **pass** | False/False/ai_short_call | – | no transcript | 0% / – | new→new (junk) guarded | – | 22 s |
| S07 Switched-off IVR, then voicemail beep | phone | 24 s | **pass** | False/False/ai_short_call | – | no transcript | 0% / – | new→new (not_connected) guarded | – | 21 s |
| S08 Hang-up after about 20 seconds | phone | 21 s | **pass** | False/False/ai_short_call | – | no transcript | 0% / – | new→new (not_connected) guarded | – | 22 s |
| S09 45-minute discovery call, proposal meeting booked | phone | 45.6 min | **pass** | True/True/– | 100% | 3% | 90% / 100% | new→new (meeting_scheduled) guarded | ok | 237 s |
| S10 2-hour workshop call, visit booked | phone | 117.9 min | **fail** | refused: 403 'This recording is longer than 60 minutes, the longest call Sales X-Ray analyses. Split it and try again.' | | | | | | |
| S10X 2 h 06 min call: over the pipeline's 2-hour limit | phone | 126.3 min | **pass** | refused: 422 'The audio length could not be verified. Try another file.' | | | | | | |
| S11 Hinglish inbound enquiry, visit booked (web upload) | web | 106 s | **pass** | True/True/– | 100% | script mixed vs devanagari | 100% / 67% | –→– (meeting_scheduled) guarded | ok | 52 s |
| S12 Marathi-English call, follow-up next Monday | phone | 87 s | **pass** | True/True/– | 100% | 23% | 90% / 100% | new→new (interested) guarded | ok | 93 s |
| S13 Hindi call with objections, brochure on WhatsApp (web upload) | web | 100 s | **pass** | True/True/– | 100% | 18% | 91% / – | –→– (interested) guarded | ok | 112 s |
| S14 Noisy line (market noise), demo booked | phone | 78 s | **pass** | True/True/– | 100% | 6% | 67% / 100% | new→new (meeting_scheduled) guarded | ok | 62 s |
| S15 One-side-silent recording (prospect not recorded) | phone | 64 s | **pass** | None/True/– | 100% | 50% | 100% / 0% | new→new (–) guarded | – | 43 s |
| S16 Crosstalk: both speak over each other during the price talk | phone | 101 s | **pass** | True/True/– | 100% | 1% | 100% / 86% | interested→interested (interested) guarded | ok | 62 s |
| S17 Speakerphone with echo, call-back on Saturday | phone | 77 s | **pass** | True/True/– | 100% | 2% | 71% / – | new→new (open_leads) guarded | ok | 51 s |
| S18 Fortline inbound: working professional, counselling session booked | phone | 78 s | **pass** | True/True/– | 100% | 4% | 89% / 67% | new→new (meeting_scheduled) guarded | ok | 52 s |
| S19 Fortline cold call to a company: phishing workshop proposal | phone | 78 s | **pass** | True/True/– | 100% | 0% | 100% / 100% | new→new (interested) guarded | ok | 62 s |
| S20 Fortline Hinglish fee negotiation, enrolled with EMI (web upload) | web | 91 s | **fail** | True/True/– | 0% | 37% | 100% / 75% | –→– (won) guarded | – | 52 s |
| S21 Fortline: student asks to be called after exams | phone | 44 s | **pass** | None/False/ai_short_call | – | no transcript | 0% / – | new→new (open_leads) guarded | – | 21 s |
| S22 Fortline: lost, prefers free YouTube courses | phone | 44 s | **pass** | None/False/ai_short_call | – | no transcript | 0% / – | new→new (lost) guarded | – | 23 s |
| S23 Meta lead turns out to be a job seeker | phone | 46 s | **pass** | None/False/ai_short_call | – | no transcript | 0% / – | new→new (junk) guarded | – | 21 s |
| S24 After the demo: meeting done, waiting on the brother | phone | 83 s | **pass** | True/True/– | 100% | 1% | 100% / 100% | interested→interested (meeting_done) guarded | ok | 55 s |
| S25 Very quiet prospect, level jumps (web upload) | web | 77 s | **pass** | True/True/– | 100% | 3% | 78% / 100% | –→– (won) guarded | – | 51 s |
| S26 Xiaomi recorder AMR (8 kHz narrowband) | phone | 75 s | **pass** | True/True/– | 100% | 5% | 82% / 100% | new→new (interested) guarded | ok | 52 s |
| S27 Stereo recording (seller left, prospect right) | phone | 77 s | **pass** | True/True/– | 100% | 3% | 90% / 100% | new→new (interested) guarded | ok | 64 s |
| S28 Marathi-English cold call, meeting booked | phone | 85 s | **pass** | True/True/– | 100% | 30% | 71% / – | new→new (meeting_scheduled) guarded | ok | 52 s |
| S29 Hindi call: parent asks about the course for his son | phone | 80 s | **pass** | True/True/– | 100% | 29% | 71% / 100% | new→new (interested) guarded | ok | 52 s |
| S30 Lost: already signed with another training firm | phone | 44 s | **pass** | None/False/ai_short_call | – | no transcript | 0% / – | interested→interested (lost) guarded | – | 22 s |

Columns: report want/got/hold (`None` = either is fine); Roles = share of words given to the right
side; WER only where transcript and script share an alphabet (S11 mixes them); Latency = upload
accepted → report or hold.

### Cost (priced by the app's own cost engine from the dev usage store)

| Calls | Audio | AI spend | Per minute |
|---|---|---|---|
| 20 full reports, 1–3 min | 31.1 min | ₹46.36 | ₹1.04–2.11 (transcription ₹0.37/min + a report of ₹1–2) |
| S09, 45.6 min | 45.6 min | ₹22.90 | ₹0.50 |
| 8 short calls held | 5.0 min | ₹1.86 | ₹0.37 (transcription only; no call minutes charged) |
| S10, S10X refused | 244 min | ₹0 | – |
| **All** | **81.6 min analysed** | **₹71.12** | **₹0.87** |

Priya's allowance after the run: 4,606 s used of 18,000.

### Findings

- **S10 (fail, high, `72235150`)**: a 117.9-minute call is refused at upload: "This recording is
  longer than 60 minutes, the longest call Sales X-Ray analyses. Split it and try again." Dev-live
  still runs the 60-minute limit; the owner's 120-minute order waits on the native release and the
  approval reseal. A phone that captured the call by itself cannot split it, and the lead keeps a
  call with no recording.
- **S10X (pass, words wrong, `c77df216`)**: 2 h 06 min is refused before any spend, but with
  "The audio length could not be verified. Try another file." instead of "too long".
- **Short calls (`6370dc55`)**: the 8 calls of 20–53 s are held `ai_short_call` as designed, but the
  transcript route answers 404 "The transcript will appear with your sales report" (no report ever
  comes), `can_upgrade` is false (no Get full report), and the panel says "The transcript is saved
  with this call". The owner's rule is transcript and lead details, with Get full report on tap.
- **S20 (fail, `12b4a31f`)**: Hindi web upload: the speaker map names the prospect, Rahul, as the
  salesperson (cue "introduced own company": he said where he works). The report itself coaches the
  right person. Lab note: the recording's seller calls himself Karan, not the account holder.
- **S15 (`ee41b4af`)**: "Forty-five thousand per seat" was transcribed "Four to five thousand per
  seat", and the report quotes that range: a tenth of the price (synthetic voice; worth a check on
  real calls).
- Not filed: the report rarely names the city or the company (the call data engine is meant to
  carry them); calls of 20–24 s with one silent side get `ai_short_call`, not
  `ai_no_conversation` (length is checked first; no report either way); S15 got a report from one
  speaker, which the rule allows on purpose (a missed speaker split must not lose a report);
  the app left the roles undecided on S24, S25, S27 and S28.

### What the seller's screens show (Priya, after the run)

- **Lead page**: each phone call once, as a call, with its recording.
- **Calls tab**: 29 calls, 21 completed, 0 processing, 0 needing attention (the 8 held short calls
  are counted in the total only).
- **Performance** (seller's own): the Saturday calls count in the 7-day view (inbound 60 attempted,
  18 connected; cold 42 attempted, 33 connected, with Priya's earlier calls); today shows 0, as the
  calls are dated Saturday. The owners' performance view and the daily call report answer 403 to a
  member, by design.
- **Home (my day)**: the do-now list is unchanged by the calls (no stage or follow-up was written,
  see *guarded*).

## Round two: the call data engine on (10 calls)

The owner approved it (1 Nov, orchestrator chat: "DO this yourself turn on"). Dev only, through the
audited Admin routes, each step logged in `/var/log/ac-owner-data-changes.log`:

- 07:16:50Z: AI spend revision 4 → 5: `background_enabled` true, `skip_sandbox` false, caps unchanged.
  The engine's fast pipeline was already enabled.
- The ₹50 daily cap had already been passed by round one's analyses (₹73 in 24 h), so the engine
  stopped at once (`ai_spend_daily_cap`). 07:28:21Z: daily cap ₹50 → ₹150 (owner via orchestrator,
  option (a), within the approved ₹280 call-test budget).
- 07:45:09Z: restored, revision 6 → 7: background off, sandbox skipped, daily cap ₹50 (as revision 4).

The 10 calls were new uploads through the fake phone as Priya, dated back to back on Friday 30 Oct
from 13:00 India time, on leads round one did not use. The fake phone waited for the engine's read
before collecting. The engine read every call 3–14 s after its transcript.

| Scenario | Result | Stage offered (want) | Moved without a tap | Lead fills (right/wrong/kept/missed) | Facts R/P (objects) | Follow-up read |
|---|---|---|---|---|---|---|
| S01 Inbound enquiry from a Meta form, demo booked | **pass** | meeting_scheduled (meeting_scheduled) | no | 1/0/2/0 | 85% / 91% (22) | ok |
| S02 Cold call, rejected: in-house trainer already | **pass** | none (lost) | no | 1/0/2/0 | 100% / 86% (15) | – |
| S03 Inbound, heavy objections, follow-up agreed | **pass** | open_leads (interested) | no | 1/0/1/0 | 87% / 100% (24) | ok |
| S04 Price negotiation on the team package, closed at 1.55 lakh | **fail** | none (won) | no | 0/1/1/0 | 78% / 80% (18) | – |
| S05 Busy prospect asks for a call back tomorrow at 6 pm | **pass** | open_leads (open_leads) | no | 0/0/2/0 | 100% / 100% (12) | wrong |
| S06 Wrong number | **pass** | none (junk) | no | 0/0/0/0 | 100% / 100% (1) | – |
| S07 Switched-off IVR, then voicemail beep | **pass** | none (not_connected) | no | 0/0/0/0 | 100% / 100% (3) | – |
| S09 45-minute discovery call, proposal meeting booked | **fail** | none (meeting_scheduled) | no | 1/0/2/0 | 90% / 100% (21) | ok |
| S17 Speakerphone with echo, call-back on Saturday | **pass** | open_leads (open_leads) | no | 1/0/2/0 | 71% / 83% (13) | wrong |
| S30 Lost: already signed with another training firm | **fail** | open_leads (lost) | no | 0/0/1/0 | 100% / 100% (11) | – |

| Measure | Result |
|---|---|
| Stage moved without a tap | **0 of 10**: no stage moved by itself |
| Stage offered | **7 of 10 right**. Meeting Scheduled for the demo (S01); Open Leads for the call-backs (S05, S17) and for the follow-up call (S03); nothing for the wrong number, the IVR and the cold rejection (lost, junk and not connected are never offered, by design). **Misses:** the closed deal (S04) and the booked proposal meeting (S09) got nothing, and the lost deal with a March check-in (S30) got Open Leads |
| Structured facts | Recall **88%** (64 of 73 key items), precision 94% on average, 140 objects. Misses: the decision maker named in passing (Sunil, Nitin), a quoted price (₹45,000), an investment figure, one objection |
| Lead fills | **5 right, 1 wrong**, 13 kept (the field already had a value: the engine only fills empty ones), 0 missed. Wrong: Company "Paddle Home Appliances" for Patil (S04, filled without asking) |
| Follow-up read | Right in 4 of 6 (S01 Tuesday 16:00, S03 Friday 11:00, S09 Wednesday 15:00 with the day). **Wrong in 2:** "tomorrow at six" said on Friday became Monday (S05), "Saturday morning" said on Friday became the next week's Saturday (S17) |
| Spend | ₹44.78 for 58.2 min (₹0.77/min), including the engine's 10 reads (₹7.41). With background on, the one-pass trial also read 5 of these calls (₹11.69). Round two ₹56.47; the day ₹127.59 |

**Why S04 and S09 got no suggestion** (`8d68f322`): the engine stores the call's outcome as
`{"enum": "deal_closed"}` (`call_data/values.py`), but `lead_desk/journey/signals.py`
`milestone_of` reads `value.get("value")`, so the outcome never counts. Its unit test feeds
`{"value": …}` and passes. A suggestion then appears only when the next step's words name a term
("demo" did; "proposal presentation" and "invoice and first installment" did not).

### The fix and its re-check (`644a6e9b5`, wb-ci 41287987725)

`8d68f322` and `deb67f5f` are fixed on dev/live in `644a6e9b5` (every Python shard the change
touches green). `milestone_of` reads the stored `{"enum": …}`, a call that ended in a no offers
nothing, and the engine's prompt dates a call by the lead's call event (the attach event's
`for_call`) instead of the upload. The new tests failed on the code before and pass after.

- **Stage offers, recomputed read-only from the stored call objects** with the fixed code and the
  sandbox's real stage list (no AI spend): S04 **Won** (was none), S09 **Meeting Scheduled**
  (was none), S30 **nothing** (was Open Leads); the other seven unchanged and right. 10 of 10.
- **Prompt date:** all 10 now read the call's Friday ("Friday 30 October 2026, 13:20 India time"
  for S05) instead of the Sunday upload.
- **Follow-ups, one fresh read each** (operator mode, the committed code; AI spend switched on
  09:06Z and restored 09:07Z, logged; ₹1.19): S05 "Tomorrow at 6 PM" → **Saturday 31 Oct 18:00**
  (was Monday 2 Nov); S17 "Saturday eleven AM" → **Saturday 31 Oct 11:00** (was 7 Nov).
- The running dev-live API and engine show this once the change ships. The one-pass report
  dates its prompt from the upload too (`reporting_pipeline.py`); that is where call data comes
  from in production, and it is not part of this fix.

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

Not tested (needs an organisation admin in the sandbox; only the owner's and Dipak's real accounts
are admins): Meta/Google webhooks with real payloads, website leads, the 5,000-row import, a seller
removed mid-day.

## Rules of the app that shaped the lab

- A phone's call is refused outside the organisation's work hours (sandbox: Mon-Sat 10:30-19:00
  India time; this ran on Sunday). The fake phone dates calls inside the last working day, back to
  back, as a phone uploading late would; the server clock was never touched.
- A recording's call must start after its lead was created, so the lab calls existing sandbox
  leads (never-used ones first) instead of new ones.
- Sign-in allows 10 attempts and one more a minute per address (shared on loopback): the fake
  phone waits on a 429. The API restarted once during the run (a deploy, 04:48Z): the fake phone
  now waits for it, as the phone's WorkManager would.
- Uploads are capped at 60 minutes on dev-live today; the pipeline itself allows 7,200 s.
- The short-call rule: under 60 s of transcript a call gets its transcript and lead details only,
  under 20 s (or under 8 s from the quieter of two speakers) no conversation; one speaker over a
  minute still counts as a conversation.

## Bugs filed (Report a problem, as the sandbox seller)

| Id | Builder | Severity | What |
|---|---|---|---|
| `72235150` | capture-setup (upload limit; the 120-minute flip) | high | S10: a 118-minute call refused at upload, "Split it and try again" |
| `c77df216` | capture-setup (upload checks) | medium | S10X: 126 minutes refused as "audio length could not be verified" |
| `6370dc55` | call analysis / report (Calls, short-call rule) | medium | Short calls: transcript never opens, no Get full report, panel says it is saved |
| `12b4a31f` | call analysis / report (speaker identity) | medium | S20: Hindi call, the prospect labelled the salesperson |
| `ee41b4af` | call analysis / report (transcription of money) | low | S15: "forty-five thousand" heard as "four to five thousand" |
| `8d68f322` | Leads (Lead OS journey signals) with the call data engine | high | **Fixed in `644a6e9b5`.** Round two: stage suggestions ignore the call outcome (`{"enum"}` stored, `value` read): a closed deal and a booked meeting get no offer |
| `deb67f5f` | call data engine (follow-up dates) | medium | **Fixed in `644a6e9b5`** (the fast engine; one-pass not yet). Round two: "tomorrow" and weekday names count from the analysis day, not the call's (late uploads move the follow-up) |
| `f04037f2` | Leads (Lead OS journey signals) | low | Round two: a clear no is never offered as Lost; a lost deal with a March check-in is offered Open Leads |
| `26cabf15` | call data engine (lead fills) | low | Round two: Company auto-filled from a misheard name ("Paddle" for Patil) without asking |
| `5605dd37` | capture-setup (call analysis / billing for the words) | high, blocks work | 0 call minutes in both sandboxes; the upload says the allowance "has been used" (still true for every seller but Priya) |
| ~~`d208a435`~~ | Leads | — | Filed in error (a 201 that returns the existing lead was read as a new one); withdrawn by `3f995945` |
| ~~`67e0ed7e`~~ | Leads | — | Filed in error (three late counts that differ by definition); withdrawn by `0ff39cb4` |

## Left in the sandbox (fictional, for clean-up with the owner's "approve delete")

AC Sales Sandbox:
- Part 2: 100 "SIM Burst 10312302 NNN" and 10 "SIM Burst 10312311 6NN" leads, 3 "SIM Dupe" leads,
  1 "SIM Due" lead with 2 call-back tasks (all `+91 00000 5xxxx`), the lead "Anil Deshmukh"
  (`+91 00000 30001`), 59 phone-logged calls on Rohan's older leads (Saturday).
- Part 1: 27 Saturday calls on Priya's existing leads (25 with recordings and reports or holds, S10
  and S10X without a recording), 4 web uploads, and Priya's 300-minute grant.
- Round two: 10 Friday calls on 10 more of Priya's leads, with the engine's facts, questions and
  6 company fills (each can be undone); 10,045 s of Priya's 18,000 left.
