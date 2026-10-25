# Demo changelog: client demo on 26 Oct 2026

Each fix for the demo: what changed, how it was verified, and what is still flaky.
Newest first. Sessions add their own lines and commit them with the fix.
No client names here.

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
- **Who did what, with their photo**, a578dd0e9: history, activity and tasks carry the person's id and photo URL for avatars. Verified by wb-ci full and e2e.

### Still flaky or open

- The digest and sweep need the Android build that shows these two push kinds, and FCM delivery on each phone brand. Production gets them with v0.92 (it is at migration 0130 tonight).
- Onboarding: a "called by" spelling nobody listed goes to the owner. Check the printed map in the dry run before applying.
