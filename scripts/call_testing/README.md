# Release call check: synthetic calls through the Play app, after every release

Owner, 13 Nov 2026: "After each new release on Play Store… really test being called… see that the
report is being generated. Then it is a confirmation that everything is working." The plan and the
options behind it: `docs/qa/call-testing-plan-20261113.md`.

## The command (after each Play release)

From the laptop with the Redmi 13 on USB, once the orchestrator has handed you the phone:

```bash
python scripts/call_testing/run.py release              # smoke: 4 calls, about Rs 11, ~15 min
python scripts/call_testing/run.py release --set full   # all 15 calls, about Rs 45, ~25 min
python scripts/call_testing/run.py release --live-ivr   # also one real call to the Jio IVR (work hours only)
python scripts/call_testing/run.py release --dry-run    # preflight and plan only, nothing pushed
python scripts/call_testing/run.py check <run-dir> --wait 10   # read an earlier run back again
```

It prints each scenario's state every minute and writes `~/ac-call-testing/runs/<run-id>/index.html`
(one page: pass or fail per scenario, seconds to report, links to the reports) and `run.json`.
Exit code 0 only when every pipeline gate passes and the app didn't crash; `--strict` also gates on
sales-or-not detection.

## What a run does

1. **Preflight.** The phone is connected and Sales X-Ray Live isn't in front (another session's
   phone). The production app's version is read. One logged, read-only query reads the QA lead "QA
   Redmi 10 Nov - test" (its number and creation), the workspace's work hours, the QA seller's
   minute account and the seller's own call times. It refuses a lead that isn't named "QA …".
2. **Audio.** The rendered library for this library version is copied from ac (`fetch`), checked
   against its manifest's hashes.
3. **Plan.** Calls are stamped back to back (3 minutes apart) in the latest working window that has
   ended, after the lead was created, clear of the seller's other calls and earlier runs.
4. **Push.** Each file gets a run-id ID3v1 tag (new bytes, so the server never treats it as an earlier
   run's file; the audio doesn't change), is named like the Xiaomi recorder
   (`<number>(<number>)_yyyyMMddHHmmss.mp3`), pushed into `/sdcard/SalesXray-QA-empty` (the app's
   recordings folder on this phone: test recordings only, never the real call-recordings folder),
   given the saved time the recorder would have given it, and checked by hash on the phone.
5. **Nudge.** The app comes to the front and its background jobs run once, so the capture scan doesn't
   wait 15 minutes.
6. **Live call (`--live-ivr`, work hours only).** One real call from the phone's SIM to Jio's toll-free
   IVR (1800 889 9999), hung up by the phone after 75 s. Only that call's recording (named for that
   number, saved after the call began) is copied into the QA folder.
7. **Check, every minute, up to 35 minutes.** One read-only query (logged once in `QUERY-LOG.txt`) by
   the files' SHA-256 only: uploaded through the dialler pickup, the plan's state and hold reason, the
   report and its sections.
8. **Finish.** Android's crash log for the app since the run began, the app still running, its own
   notices, the measured spend from the usage export, the page. The pushed files are removed from the
   phone once every one has reached the server.

## What is judged

- **Pipeline (gates the release):** a report scenario needs a summary, a verdict, at least one strength
  and one improvement, 8 dimensions, 9 sections and a next-call focus (the coaching mission). A hold
  scenario needs the server's hold (`ai_short_call` / `ai_no_conversation`). A scenario may also allow
  either ("any").
- **Sales or not (measured):** a hold means "not a conversation"; a report counts as a sales verdict
  unless it stores a call purpose. On 13 Nov 2026 production stores none, so the personal, internal and
  support calls are coached as sales calls. That's the known gap the non-sales scenarios measure.

## The library (`scenarios.py`)

| Id | Call | Expected |
|---|---|---|
| R01 | Builder's executive to a first-time buyer, site visit (English) | report, sales |
| R02 | Broker to a flat owner selling, listing mandate (Hinglish) | report, sales |
| R03 | Broker to an investor, hard price negotiation (English) | report, sales |
| R04 | Builder's executive to an NRI buyer, video tour (English) | report, sales |
| R05 | Cold call turned down (English) | report, sales |
| R06 | Pune family, 2BHK, visit on Saturday (Marathi-English) | report, sales |
| R07 | Course counsellor to a parent, demo class (Hinglish) | report, sales |
| R08 | Closing call, booking amount (English) | report, sales |
| R09 | Wrong number (Hinglish) | a hold, not sales |
| R10 | Personal call with family (Hinglish) | report or hold, not sales |
| R11 | A bank's IVR menu (English) | report or hold, not sales |
| R12 | Internal call with the sales manager (English) | report or hold, not sales |
| R13 | Support complaint from an existing buyer (English) | report or hold, not sales |
| R14 | Dead air, 65 s | no conversation |
| R15 | The network's "switched off" message | no conversation |

The smoke set is R01, R06, R10 and R14. Everything is fictional; voices are offline piper voices.

## Rendering the audio (on ac, once per library change)

```bash
~/bin/simlab /home/acdev/simlab/.venv/bin/python scripts/call_testing/generate.py \
  /home/acdev/simlab/call-testing --voices /home/acdev/simlab/voices --python /home/acdev/simlab/.venv/bin/python
```

`generate.py` renders through the simulation lab's `synth.py` (the far side band-limited like a phone
line), pads dead air with faint line noise, and writes `<library sha[:12]>/manifest.json`.

## Rules

- The Redmi 13 (`7505cec`) only, one driver at a time: take the lock from the orchestrator first. Never
  the Note 8 Pro (refused in code). Never install or touch Sales X-Ray Live.
- Production writes happen only on the QA lead, through the app itself. Reads go only through ac's
  logged read-only path, by this run's file hashes.
- Spend: a report costs about Rs 3.5 on production, a hold about Rs 0.3. Keep runs small; the page shows
  the measured spend once the usage export (every 30 minutes) has the calls.
