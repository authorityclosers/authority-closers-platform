# Demo changelog: client demo on 26 Oct 2026

Each fix for the demo: what changed, how it was verified, and what is still flaky.
Newest first. Sessions add their own lines and commit them with the fix.
No client names here.

## Facebook lead sources (Meta-suite session): bug reports #7, #8, #10, #12, #13, #14

- **Meta leads already in the leads are linked, not repeated; new ones go through the duplicate engine (P0)**, this commit.
  - Found on production (counts only, logged as `fb10*.sql`):
    - AC's Page was switched on at 18:23Z, 25 Oct.
    - Its older-leads run read 102 leads and filed 100 as repeats onto the leads imported from a file.
    - That reset 94 follow-ups to 18:24 and added "Asked again" lines. None reopened.
    - It said "none added".
  - What changed:
    - A Meta lead whose person is already a lead made at or after the form was sent gets one note on that lead (Meta lead id and source). Nothing else changes.
    - A newer form is still a repeat.
    - New Meta leads are rescanned at once. A certain pair is merged (undo within 30 days); any other pair goes to the review queue.
  - Verified by:
    - `test_meta_backfill.py` and `test_duplicate_intake.py`.
    - `test_lead_desk_meta_postgresql.py`: 4 imported leads and the Page connected give 0 new, 4 notes, and Lost stays Lost. A newer Meta lead with a known email is merged.
    - wb-ci targeted run 40224272062.
  - Open: putting the 100 AC leads back is a data change waiting for the owner's approval. Until v0.93 is live, nobody presses "Bring in older leads" on AC's Page.

## P0: Admin bug panel (sign-in session)

Production bug panel, exported 25 Oct ~16:00Z through the logged read path (`/home/suyash/costq`,
`bugs1.sql`; words masked). There are 8 reports, #1–#8. All were filed on 25 Oct evening, in the AC
org, and all are still `new`. Grouped by root cause:

| Cause                                                                           | Reports        | Owner             | State                                                |
| ------------------------------------------------------------------------------- | -------------- | ----------------- | ---------------------------------------------------- |
| A. Report-a-bug must work from every screen, menus open too, with a PC shortcut | #5             | sign-in           | fix in CI                                            |
| B. Organisation analytics are empty although sellers called                     | #4             | sign-in / Android | diagnosed; see "Still flaky"                         |
| C. Facebook lead sources: adding Pages, a second account gets "App not active"  | #7, #8         | sign-in           | help text in CI; full Page and form management later |
| D. Leads UI polish (#1, #2, #3) and naming Calls "Coaching" (#6)                | #1, #2, #3, #6 | builder           | sent to the builder                                  |

### Known issues from the brief, checked on production

- **Simulated call mode: off for real and new orgs. Verified, no change needed.**
  - The server sets `call_mode` to `simulated` only for orgs in `conversation_sandbox_organisations`.
  - Only approved data-change scripts write that table, never org creation.
  - In production, 2 of 7 orgs are sandboxes: the synthetic load org and the AI-directory reviewer org.
  - All 44 call events in the AC org since 20 Oct have `simulated=false` and no sample (`bugs2.sql`, `bugs5.sql`).
- **Every call carries the seller's person id: verified.**
  - 0 of 46 call events in real orgs since 20 Oct lack an actor.
  - Recordings require a `person_id` (`bugs4.sql`).
- **Analysis starts for every new recording: verified for recordings that reach the server.**
  - Every non-deleted recording in a real org since 15 Oct has a processing plan and a started first stage. None is stuck "not started" (`bugs3.sql`, `bugs6.sql`).
- **Large-font layouts:** the builder.

### Fixes

- **Report-a-bug (A, #5)**, a572dd29f.
  - What changed:
    - Ctrl B (⌘B on a Mac) opens the reporter from any screen, with a menu or sheet open too.
    - Shake opens it over menus and sheets too, but not over the reporter.
    - Statuses read Received → Fixing → Solved in the app, and the "solved" corner card says Solved.
    - Each report carries the last 20 app steps: telemetry event names, times and route templates, never content. The server cleans them and Admin shows them as "Last steps in the app".
    - The reporter was already on in every org, new ones included, with no per-org switch.
  - Verified by:
    - unit tests: `open.test.ts` (shortcut), `my-reports.test.ts` (words), `trail.test.ts` (20 steps), `test_bug_report_scrub.py` (server keeps 20 well-formed steps only);
    - wb-ci --full 40210818306 (all green but mypy, fixed; lint 40211813646) and --e2e 40211606997.
- **Facebook lead sources (C, #7, #8)**, 51219e766.
  - What changed: Sources → Facebook & Instagram gains "Connecting another Facebook account or Page?". It covers:
    - which account Facebook uses;
    - that "App not active" means the account must be added while Meta reviews the app, and to report it;
    - how to get access to a Page someone else runs.
  - Verified by: `sources-view.test.tsx`.

- **Empty analytics explained (B, #4)**, the commit that adds this line.
  - What changed: the organisation overview's empty state reads "No analysed calls in the
    last 30 days" and says a call logged without its recording isn't analysed, and to add
    the recording from the lead.
  - Verified by: `organisation-view.test.tsx`; wb-ci --web 40212885213.

### Still flaky or open

- **Recordings from phones (B, #4).**
  - Of the AC org's 46 calls logged since 20 Oct, only 2 carried a recording; those 2 were analysed.
  - The rest were logged without the recording, so organisation analytics stay empty.
  - This is the Android recording pickup (P1 step 5), with the xiaomi-call-recordings session.
  - Analytics could also show logged calls with no recording; not done tonight.
- **Facebook:** connecting more than one account, a list of every form, and managing forms in one place are not built. Accounts outside the Meta app's testers can't connect until Meta's review passes.
- **Marking the 8 reports Solved in production:** waiting for the fixes to be live and for the orchestrator's go-ahead.

## P2 onboarding and notifications (Lead OS session)

### Fixes

- **Onboarding in one command (P2)**, c5b9f1fb4.
  - What changed: `scripts/data-changes/onboard-organisation.py` makes, in one transaction:
    - the org, with calls from the sellers' own phones (never simulated);
    - the owner's and sellers' accounts, so their first Sign in with Google joins them;
    - the sheet as leads, with +91 numbers, exact repeat rows dropped and every column kept;
    - each lead given to the seller its "called by" names, by listed variants only; blank or unlisted goes to the owner;
    - the sheet's follow-up dates as next calls at 10:00 IST;
    - the Play opt-in link and the tester emails, printed.
  - Dry run by default; a rerun with tonight's sheet adds only new rows.
  - Verified by: a dry run on dev with a messy 300-row fictional sheet (284 leads, 10 repeats dropped, 161 follow-ups, 9 s, rolled back); `test_onboard_organisation_data_change_postgresql.py`; wb-ci full and e2e.
- **10 AM digest and 2-hourly sweep (P1 steps 10, 11)**, 49b3aeba5 (migration 0137).
  - What changed:
    - "Today: N follow-ups" at 10:00 IST; overdue and new-lead counts at 12, 14, 16 and 18 IST.
    - Each goes once per seller (a ledger), inside work hours. The push carries counts only; the words come from `GET /v1/lead-desk/alert?kind=digest|sweep` on the seller's own session.
    - `scripts/data-changes/send-digests-now.py` sends them now to a test org, through the same code.
  - Verified by: `test_digests.py`, `test_lead_desk_digests_postgresql.py`, the 0137 migration and backup-parity tests; wb-ci targeted, full and e2e.
- **Red banner for a follow-up due within the hour (P1 step 12)**, 5b073299b.
  - What changed: the app asks `GET /v1/lead-desk/soon` every minute and on focus. It raises a red top banner with the urgent haptic, "<lead>: follow-up in 40 min", with Open going to the lead. Once per follow-up; quiet outside work hours.
  - Verified by: `due-soon.test.tsx`, `test_lead_desk_digests_postgresql.py`; wb-ci full and e2e. The 360/390 matrix is on `/review-fixture/alerts?level=due`.
- **Leads setup: Stages and Sources open on a tap**, 77b722e90.
  - What changed: the part row read its part from the address only, which a bare `history.replaceState` doesn't refresh, so a tap changed the address but not the page. A tap now shows its part at once and keeps it in the address (Connections too). Every tile's note wraps to two lines, and first-call times read "22h 38m". The Sellers rows' "1/50 open" is that seller's real limit (no change).
  - Verified by: `org-hub.test.tsx`, `words.test.ts`; wb-ci full and e2e.
- **The sales team's eight stages**, eaf7dfa88 (v0.93): New lead, Not connected, Discussion incomplete, Interested, Meeting/Demo scheduled, Meeting/Demo completed, Won, Lost.
  - What changed:
    - Junk is no stage: a lead that was never real is Lost, "Junk / not a real lead". The board has no Junk column.
    - Pipeline numbers count it, and "Merged into another lead", as Junk, never as a lost deal.
    - New organisations start on these stages.
    - Organisations on the old nine move by `lead-stages-template.py`, their Junk leads going to Lost with that reason (production after the owner's approval).
  - Verified by: `test_transitions.py`, `test_journey.py`, `test_reports.py`, the acceptance, pipeline-report, merge, onboarding and stages-script database tests; wb-ci full and e2e.
- **Onboarded sellers skip "A few details"**, eaf7dfa88: `onboard-organisation.py` now writes each person's profile phone (and name when empty), never over a phone they set, so a seller goes from Sign in with Google straight to the terms. Verified by `test_onboard_organisation_data_change_postgresql.py`.
- **Switches answer a tap at once**, 16f0c77a4 (Admin bugs #1 and #2): Taking new leads and every switch on the same pattern give a haptic and a pressed look on the tap, show the new state before the save returns, then a short "Taking new leads: On" and a success haptic; a failed save goes back, with the error haptic and its corner card. Verified by `state-switch.test.tsx`, `phone-panel.test.tsx`; wb-ci full and e2e.
- **The red banner on a 320 px phone**, 1c36f6d17: Open goes under the words, so a long lead name wraps between words. Verified by the 320/360 matrix; wb-ci full and e2e.
- **After a call, the lead fills itself and can be put back** (v0.93, owner's after-call chain, server side):
  - What already existed: name, company, city and interest filled from the call only into empty or AI-filled fields, never over a person's value; the rest asked one at a time.
  - New:
    - Each fill names the fact that made it and what the field held before. "Filled in for you" says `can_undo`, and `POST /v1/sales-xray/call-data/objects/{id}/undo-fill` puts the field back in one tap, only while nobody has changed it since. The fact becomes "rejected", so the same words don't fill it again.
    - The lead's history says "filled from the call" (`via: "call"`); an undone fill and its undo are not shown.
    - A suggested WhatsApp or SMS after the newest call, in its language (English, Hinglish, Hindi or Marathi): thanks, and the agreed next talk while it is still ahead. Fixed wording, no model; sending only opens WhatsApp or SMS, keeping the key `after_call`.
  - Not yet: starting the analysis by itself after every call needs a standing consent (a design for the owner); the screens are the builder's.
  - Verified by: `test_call_data_after_call_postgresql.py`, `test_call_data_http_postgresql.py`, `test_call_data_reply.py`; wb-ci full and e2e.
- **Who did what, with their photo**, a578dd0e9: history, activity and tasks carry the person's id and photo URL for avatars. Verified by wb-ci full and e2e.

### Still flaky or open

- The digest and sweep need the Android build that shows these two push kinds, and FCM delivery on each phone brand. Production gets them with v0.92 (it is at migration 0130 tonight).
- Onboarding: a "called by" spelling nobody listed goes to the owner. Check the printed map in the dry run before applying.
