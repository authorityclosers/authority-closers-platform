# Gold review on the phone — owner order, 19 Oct 2026

The owner asked for a clean, phone-first review flow so Dipak (and any
reviewer) can build the gold dataset quickly: alerts for new Reports, one line
at a time, the evidence on top and big choices below, and figures.

## What changed

- **Review in the Sales Xray app** (`/review`, `/review#call=<id>`,
  `/review/figures`). It is what the Android app shows, in the app's look.
  - Queue of the reviewer's real Reports: waiting calls and lines, today,
    total, time per line, agreement with the AI, Start/Carry on.
  - One line at a time, 29 per call (27 pointers, Final Call Outcome,
    Coaching). Top half: pointer, the AI status and score labelled
    **AI draft**, what the AI said, the quoted lines with the lines either
    side, speaker and **play-from-here**, the AI's advice, and the call
    summary. Bottom half: Agree / Partly / Disagree; for Partly or
    Disagree, the right status (the AI's pick marked), a score stepper, up to
    six reason chips and an optional note. Back, Skip with a reason, and Next.
    Agree saves and moves on at once. Saves run in order in the background,
    each superseding the line's newest save. A progress bar shows the count.
  - Figures: gold-set size, calls, reviewers, today, agreement, time per
    line, skips, where the AI is wrong most (with score gap and top reasons),
    between-reviewer agreement, AI-status coverage, thinnest lines, the
    reviewer's last 14 days, every line, and a per-reviewer table for the
    operations owners/admins.
  - Alerts: a Review entry on the rail and a Review chip in the phone top bar
    (gold reviewers only, with the waiting count). A corner card "New Report
    to review" appears with a Review button when a newer Report is waiting.
    The count is read on open, when the app returns to the front, and every
    two minutes. Phones keep their five tabs (owner, 17 Oct).
- **Back end** (`d5116a31`): `/v1/sales-xray/review/{badge,queue,metrics,
  assignments/<id>, assignments/<id>/lines, assignments/<id>/source}` on the
  Sales Xray host. Account sessions are admitted only for a verified,
  standing, unrevoked gold reviewer acting outside any workspace, and only on
  that person's own gold assignments
  (`AccountGoldReviewService._reviewer`). Everything else is the 16 Oct gold
  service: assignment, source, retention, expiry, revocation and
  transcript-revision guards, append-only rows with supersede, and erasure.
  The admin reviewer audio route and the new route share one streamer.
  - `GoldSave`: the note is optional (owner spec). A save can also carry a
    corrected status, reason codes, a skip reason and the seconds spent. The
    server stores the AI status and score that the line judged. It never
    stores quotes.
  - Metrics are counts only.

## Checks (on ac, workbench)

- PostgreSQL: `tests/database/test_sales_xray_review_postgresql.py` (new: contract,
  reviewer account review + saves + queue + badge + metrics, refusals for
  non-reviewers, workspace-scoped actors and owner figures) with
  `test_gold_reviews_postgresql.py` and the gold unit tests: **28 passed**
  (`strikes/1801/sx-review-pg-20261019.log`). The unit test that required a
  note now asserts the note is optional.
- Ruff, format, focused mypy: clean. The first back-end commit message said
  mypy was clean before it was. Six typing errors in the metrics loop were
  fixed in the web commit.
- Web: prettier, eslint (review + shell) clean; `tsc --noEmit` 0 errors;
  vitest `app/review` (new flow test: evidence shown, Agree saves and
  advances, Partly sends status/score/reasons, Skip saves a skip, empty fields
  dropped), `app/shell`, `app/ui` (raw-colour ratchet), owner-surfaces,
  layout, page: all pass.
- Browser, 390 × 844, light and dark: the real `/review` page on the workbench
  dev server (`127.0.0.1:3026`), with every review API answered by fictional
  data and saves intercepted. Queue → item → Agree → Disagree with status, score
  and reason → Skip → figures. No page errors and nothing clipped, except the
  scrollable chip rows and the reviewers table. Captures:
  `strikes/1801/shots/2026-10-19/{1-queue,2-item,3-disagree,4-skip,5-figures}-390-{light,dark}.png`.

## Data

- Dev: `dipak@authorityclosers.com` designated as a gold reviewer under the 16 Oct
  approval (ecff5661). Dry-run first, then apply, run `ab979253`, approver
  admin@. Receipt: `strikes/1801/gold-designate-dev-apply-20261019.json`.
  The existing reader then assigned him **34 real dev Reports**.
- Production: not touched here. Release and the production designation go
  through Align 3 and the owner's dry-run.

## Push to the phone — what it needs

The Android app (`authorityclosers/sales-xray-apps`, Capacitor 8) already
receives Firebase pushes for Lead alerts. Dev has the FCM settings. But
`LeadAlertService` only accepts `type=lead_desk`, and `LeadAlerts.show` only
opens `/leads…`. A review push needs:

1. Apps repo: accept `type=gold_review`, read the words from
   `/v1/sales-xray/review/badge` on the reviewer's session, and open
   `/review#call=<id>`. Add a "Review alerts" channel. Then build and publish a
   new APK (owner approves the `android-release` run).
2. Server: a small sender beside `lead_desk/push.py`. It reuses the
   registered `LeadDevice` tokens and FCM, and sends ids and a count only, when
   the gold reader creates an assignment.
3. Production FCM settings (`AC_FCM_*`). The dev API env has them. They were
   not found in the production host env files, so check Infisical before
   relying on production push.

Until then, the alerts are the in-app chip, the corner card, and the Pulse
subtask per assignment (`ac-pulse-gold-bridge`, Align).

## Push to the phone — built (19 Oct)

Server (`lead_desk/review_push.py`, wired in `lead_desk/push.attach`):

- A separate bounded reader in the API, beside the Lead Desk sender. The gold
  reader job is unchanged and stays provider-free.
- Every 30 seconds, under advisory lock 1802/1264, it finds gold assignments
  from the last two hours that were not alerted yet. It skips revoked
  reviewers, revoked or expired assignments, and deleted calls. It sends only
  to reviewers who have a registered phone: the `LeadDevice` tokens of that
  person in any workspace, with each phone sent once.
- The FCM data carries ids and a count only:
  `{type: gold_review, kind: one|many, assignment, alerts, count}`. `count` is
  the reviewer's waiting number from the review badge.
- Each alerted assignment gets one append-only audit event,
  `conversation.gold_review_alerted`, in the call's workspace chain. That is
  also the "already sent" record, so there are no table changes. Dead phone
  tokens are forgotten.
- Assignments from one reader pass become one push, so a first designation
  buzzes once with "N Reports to review" instead of up to twenty times.
- It is off until `AC_FCM_*` exist. Dev has them; production does not yet.

Phone app (`authorityclosers/sales-xray-apps`, branch `gold-review-alerts`):

- `type=gold_review` gets its own "Review alerts" channel.
- The words come from `GET /v1/sales-xray/review/badge` on the reviewer's own
  session.
- The alert opens `/review#call=<assignment>`, or `/review` for several.
- Alerts may only open `/leads` or the review pages.
- An APK publish needs the owner's `android-release` approval.

Checks on ac:

- `tests/database/test_gold_review_push_postgresql.py`, run with fictional data
  and a fake FCM transport: 3 passed. They prove one push per new assignment
  to the reviewer's phones only, never to the seller, never twice, and nothing
  older than two hours. Dead tokens are dropped, and a revoked reviewer gets
  nothing.
- Together with `test_sales_xray_review_postgresql`, `test_gold_reviews_postgresql`
  and the Lead Desk tests: 45 passed and 1 failed. The failure is
  `test_empty_gold_migration_downgrade_and_reupgrade`. Its metadata diff
  includes check constraints on `conversation_report_settings_events` (0098,
  7df03d79), a table this change does not touch.
- Ruff, format and mypy are clean.

Dev proof: `strikes/1801/gold-push-dev-proof-20261019.{py,log}`.

- It replays every real dev reader pass through the sender, with a fake phone
  per standing reviewer and a fake FCM transport, in one transaction that is
  rolled back.
- Result: 35 assignments came from 3 passes, which made 3 pushes (19, 15 and
  1 new Reports). Each assignment was recorded exactly once, and a later pass
  sent nothing.
- After the rollback, no proof device or audit row was left.
- `count` shows today's total in this replay.

The reviewer's phone must be registered once. Today that happens through
Leads → "Turn on alerts" in the Android app, inside an organisation workspace.

## Turn on review alerts from /review (19 Oct)

A reviewer can now turn on alerts where they review. Leads and an
organisation workspace are not needed.

- **Card on /review:** shown only inside the Android app, under the title,
  once. It says "Know when a new Report is ready" and has a "Turn on alerts"
  button.
  - If the phone refuses notifications, it says how to allow them.
  - "Not now" hides it on this phone.
  - When alerts are already on, it shows nothing and quietly re-sends the
    phone's current alert address.
- **`GET /v1/sales-xray/review/push`:** the app's Firebase client settings
  (public, no secrets). Standing gold reviewers get them; everyone else gets
  `enabled: false`, so the card never shows.
- **`POST /v1/sales-xray/review/devices`** (same-origin, standing reviewers
  only):
  - It uses `review_push.register_phone`, which reuses Lead Desk's phone
    registration (one owner per phone, newest five per person).
  - The phone is kept under the reviewer's operations or public learner
    workspace when they have one, so review alerts never turn on lead alerts.
    Otherwise their current workspace, otherwise any active one.
  - With no active workspace at all, it refuses with a plain message.

Checks on ac:

- `test_gold_review_push_postgresql`: 4 passed, including a new registration
  test (a non-reviewer is refused; a quiet workspace comes first).
  `test_sales_xray_review_postgresql`: 3 passed.
- The API module imports, and both routes build their OpenAPI.
- Ruff, format and mypy are clean.
- Web: vitest `app/review` (with the review fixtures) has 9 files and
  34 tests, all passed; 6 of them are new card tests. Prettier and ESLint are
  clean, and `tsc --noEmit` exits 0.
- Captures: `strikes/1801/shots/2026-10-19/alerts/`.
  - Real /review on the workbench dev server, inside a stand-in phone app
    (SXPhone bridge and app user agent), with fictional data.
  - 390 px, light and dark: the offer, after turning on (the card is gone and
    one registration was sent), and refused (no registration).
  - No overflow and no page errors.
