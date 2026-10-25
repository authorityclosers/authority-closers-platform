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

- **Report-a-bug (A, #5)**, commit SHA to come.
  - What changed:
    - Ctrl B (⌘B on a Mac) opens the reporter from any screen, with a menu or sheet open too.
    - Shake opens it over menus and sheets too, but not over the reporter.
    - Statuses read Received → Fixing → Solved in the app, and the "solved" corner card says Solved.
    - Each report carries the last 20 app steps: telemetry event names, times and route templates, never content. The server cleans them and Admin shows them as "Last steps in the app".
    - The reporter was already on in every org, new ones included, with no per-org switch.
  - Verified by:
    - unit tests: `open.test.ts` (shortcut), `my-reports.test.ts` (words), `trail.test.ts` (20 steps), `test_bug_report_scrub.py` (server keeps 20 well-formed steps only);
    - wb-ci --full RUN.
- **Facebook lead sources (C, #7, #8)**, commit SHA to come.
  - What changed: Sources → Facebook & Instagram gains "Connecting another Facebook account or Page?". It covers:
    - which account Facebook uses;
    - that "App not active" means the account must be added while Meta reviews the app, and to report it;
    - how to get access to a Page someone else runs.
  - Verified by: `sources-view.test.tsx`.

### Still flaky or open

- **Recordings from phones (B, #4).**
  - Of the AC org's 46 calls logged since 20 Oct, only 2 carried a recording; those 2 were analysed.
  - The rest were logged without the recording, so organisation analytics stay empty.
  - This is the Android recording pickup (P1 step 5), with the xiaomi-call-recordings session.
  - Analytics could also show logged calls with no recording; not done tonight.
- **Facebook:** connecting more than one account, a list of every form, and managing forms in one place are not built. Accounts outside the Meta app's testers can't connect until Meta's review passes.
- **Marking the 8 reports Solved in production:** waiting for the fixes to be live and for the orchestrator's go-ahead.
