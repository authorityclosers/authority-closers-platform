# Call capture setup

Owner, 30 Oct 2026: "it can be made simple and kind of compulsory before moving into the app, so simple clicks
and disclosure one by one, so that all our old as well as new users have to agree and finally get the nice
experience of all of this."

Every seller goes through one guided flow before Home, Leads and Calls. Each screen has one sentence on why and
one primary button. Before this, call capture was four separate controls in Settings, Calls, and few sellers
turned it on.

## The steps

1. **Your name and phone.** The profile that the upload's `write-eligibility` check reads. Without it, every
   upload gets a 403 at the edge. An Indian 10-digit number is saved with +91.
2. **What Sales X-Ray captures and why.** Five plain lines (the folder is checked also when the app is closed;
   only calls with a lead's number and a matching time; 60 seconds to Undo; analysed at the organisation's AI
   setting; encrypted, deletable), then the owner's approved standing-consent words, as sealed, with the upload
   terms' privacy details.
   - **I agree** records the standing consent through the existing path (`POST /v1/sales-xray/call-ai/auto-analysis`).
     Nothing is pre-ticked, and nothing is remembered from an earlier screen.
   - **Not now** is recorded as a no. The seller goes into the app. The flow asks again the next day.
   - Someone who agreed before sees the same screen with "You agreed on <date>" and **Continue**.
3. **Pick your call recordings folder.** Android's folder picker (`pickRecordingsFolder`). Uploads need this
   folder grant (`AutoCapture.configure` refuses without one). It says which phones save calls by themselves.
   - If the folder is chosen but the Phone app's recording switch is off: the brand's steps and **Open call
     recording settings**.
   - Google's Phone app keeps its recordings private: the screen says so, and offers another Phone app where one
     is installed.
4. **Let Sales X-Ray run in the background.** Android's battery question. On brands that stop apps after a
   restart (Xiaomi, Vivo, Oppo, Realme, OnePlus, Huawei), Autostart follows.
5. **Turn uploads on.** Upload notices first (Undo needs them), then the app's own confirmation with the words.
   Then **You're set**: what is on, and when the phone's newest call recording was saved.

## Who, where and when

| | Organisation (owner, admin, manager, member) | Viewer, Finance | Personal workspace |
|---|---|---|---|
| Phone app | Required on Home, Leads and Calls; all five steps | Never | Once per phone, every step skippable; no consent or uploads (calls upload by themselves only in an organisation) |
| Web | Steps 1 and 2, then "Now finish on your phone" | Never | Never |

- **Required until:** the name and phone are in, the seller agreed, and (in the phone app) this phone finished.
  A fresh install has a new install id, so it goes through the flow again.
- **Existing users** see it once after updating: no phone has finished yet.
- **A no stands for one day** (`ASK_AGAIN_AFTER`). Turning the consent off in Settings, Privacy counts the same way.
- **Settings and Team stay open** while it is required, so nobody is stuck.
- **A failed read never locks anyone out.** If the check can't reach the server within 10 seconds, nothing
  opens.
- **An app too old** to upload by itself gets steps 1 and 2, then "Update Sales X-Ray".
- **Order with other first-run screens:** the Terms card goes first, then Home's first run, then this. "Set up
  this phone" waits until it closes, then asks only for what is still missing.
- Settings, Privacy, Calls has **Go through call capture setup** to open it again, never required.

## The record

`packages/python/ac_platform/call_ai/capture_setup.py`. No migration: append-only audit events, like the standing
consent (`auto_consent.py`).
- Resource `sales_xray_capture_setup`, resource id = the person's id, in the organisation's chain.
- Action `sales_xray.capture_setup.v1`.
- `outcome: completed` names the phone: install id, model, family, app version, and whether the folder, background
  and uploads were on. It never stores a call, a lead or a number.
- `outcome: declined` is a no at the disclosure.
- The newest event is the seller's last word. Each phone keeps its newest finish.

A finished phone is refused (409/403) until the consent is on and the profile is complete, so the record can't
claim more than the seller did. A no is refused while the consent is on: that is turned off in Privacy.

## API

All on the Sales Xray app host, `Cache-Control: private, no-store`.
- `GET /v1/sales-xray/call-ai/capture-setup`: the caller's own state (required, profile, consent, last no, when to
  ask again, finished phones). A personal workspace answers `required: false`.
- `POST /v1/sales-xray/call-ai/capture-setup` with an `Idempotency-Key`: `{"outcome": "completed", "phone": {…}}`
  or `{"outcome": "declined"}`.
- `GET /v1/sales-xray/call-ai/capture-setup/team`: owners, admins and managers. Each seller's state: `set_up`,
  `phone_pending` (agreed, no phone yet), `declined`, `turned_off`, `consent_changed`, `not_started`. Not set up
  first.

## Team

Settings, Team & roles shows **Call capture** to owners, admins and managers: "2 of 5 not set up", each seller
with one line on why ("Said not now on 29 Oct. Asked again daily.", "Agreed, but hasn't opened the app on a phone
yet") or their phone's model.

## Check it

- Review fixture: `/review-fixture/capture-setup?step=profile|consent|recordings|recorder|private|background|autostart|uploads|done|web|update|personal`,
  `&agreed=1` for the agreed consent screen, `?view=team` for Team.
- Tests: `apps/sales-xray-web/app/capture-setup/*.test.ts(x)`, `app/organisation/capture-setup-panel.test.tsx`,
  `tests/unit/call_ai/test_capture_setup.py`, `tests/database/test_capture_setup_postgresql.py`.

## Fix 5: permissions after sign-in, the recording check, the owner's count

Owner order, 30 Oct 2026 (14:35Z).

**Permissions checklist** (`app/capture-setup/permissions-gate.tsx`, rules in `permissions-rules.ts`):
- In the phone app, right after sign-in, one screen lists five items: call log, phone, contacts, notifications and the
  recordings folder. Each has **Allow**. Once Android won't ask again, the button becomes **Open settings**.
- It covers every page until everything this app build can grant is granted. There is no Not now. Agreeing to call
  capture stays its own choice: its no is still recorded and asked again a day later.
- **Nothing locks anyone out over what the build can't ask for:**
  - Contacts are offered but never waited on until the owner states what they are for (orchestrator, 30 Oct 2026).
    They need an app build that declares them (`checks.contacts`, apps PR #18, not merged); other builds say "Update
    Sales X-Ray".
  - Builds without the folder picker say the same for the recordings folder.
  - The Google Play build has no call history until Google approves the declaration: "Comes in a later Google Play
    version".
  - Call logging works only in an organisation's workspace (the phone refuses it in Personal), so there it never
    blocks.
- **Order of screens:** the Terms card, then Home's first run, then this checklist, then call capture setup, then "Set
  up this phone".

**Recording check** (`app/capture-setup/recording-check.tsx`, server `call_ai/missing_recordings.py`):
- A connected lead call (India time, today) with no recording two minutes after it ended counts as missing. Private
  and sample calls are left out. The count never names the lead, its number or the audio.
- `GET /v1/sales-xray/call-ai/capture-setup/missing` returns the seller's own count and newest time.
- The card shows above the bottom bar with the phone's Phone-app steps: this phone's make when the app knows it,
  else Xiaomi/HyperOS's first. In the app it adds **Open call recording settings**.
- **Done** hides the card until another call is missing. It never shows over a setup screen.

**Owner's count:** Team's Call capture shows "N calls without a recording today" for everyone and per seller (`GET
.../team` adds `missing_today`). Home is left alone (another session owns Home's numbers).

No migration and no change to lead or call data: all reads.

## Not in this change

- Flow telemetry (`useFlow`): the server's flow names are a closed list; adding `capture_setup` is its own change.
- Hindi and Marathi: the consent words wait for review, as for automatic analysis.
