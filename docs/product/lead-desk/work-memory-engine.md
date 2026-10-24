# Work memory engine: notes, tasks, reminders and the next best action (design, 24 Oct 2026)

Owner, 24 Oct 2026, after a seller's day on 383 leads: "NOT A VIEW, A WELL PLANNED
ALGORITHM WITH PROPER ENGINE AND WELL TESTED". The seller notes "send WhatsApp",
"email the brochure", "call back at 5:30", and nothing reminds her or shows them later.

This engine is the seller's work memory. Every screen (the lead page, Tasks, My work,
Notes, Home's "Recently called", the board) is a window onto it. Screens come after the
engine passes the acceptance list in section 10.

## 1. Principles

1. **One record of the seller's work.** Every interaction is an append-only event on the
   lead (`lead_desk_events`): a call, its outcome, a note, a WhatsApp or email message, a
   stage move, a task. No event is edited or deleted except by the lead's deletion, which
   counts them.
2. **Idempotent writes.** Every command carries a `command_id` made on the device. The same
   command twice changes nothing the second time and answers the same state. This is the
   rule that already guards calls, notes and moves (`LeadDesk._command_seen`).
3. **A task is state; its history is events.** `lead_desk_tasks` holds what is open now.
   Each change also writes one `task` event, so the lead's timeline and My work show it.
4. **Nothing is created silently.** Extraction proposes; a person confirms in one tap.
5. **Explainable.** Every reminder, rollover and ranking can say why ("because: promised
   5:30 call, 20 min overdue").
6. **Pure where it can be.** The time-phrase parser, the extractor, the reminder planner and
   the ranker are pure functions over facts and a clock. They are tested without a database,
   with property tests where rules must hold for every input.
7. **The desk's day is India time** (`store.IST`, as `_day_start` already counts). IST has
   no daylight saving, so times never skip or repeat.

## 2. Data model

### 2.1 What exists and stays

| Piece | Use in the engine |
|---|---|
| `lead_desk_events` (kinds `call`, `result`, `note`, `message`, `stage`, `meeting`, `scheduled`, `suggestion`, ...), `command_id`, `actor_person_id`, `ix_lead_desk_event_actor` | The one record. New kinds: `task` and `email` (migration A). Proposals use the existing `suggestion` kind. |
| `Lead.next_action_at`, `next_action_note` | Kept as a **projection**: the earliest open task of the lead's owner. Written only by the task writer, so every reader and the push sender keep working. |
| `Lead.alerted_due_at`, `LeadMeeting.reminded_for` | Replaced by the reminder ledger (2.3) once tasks ship. The old fields stay until a later clean-up. |
| `lead_desk_meetings` | A meeting is a task of type `meeting` with start, end and location. The meeting row keeps its Lead OS rules (one scheduled meeting per lead), and its task is linked by `task_id`. |
| `lead_desk_whatsapp_messages`, social messages | Messages already stored. The timeline shows each one (not one line a day), and the extractor reads their text. |
| `hours.py` (work hours), `sla.py` (first response) | Quiet hours, and SLA facts for the ranker. |
| `push.py` (FCM, data-only, words fetched on the seller's own session) | Reminder delivery, unchanged. |
| Call Reports (AI, when on) | Their next steps become proposals of the same shape as the rules' proposals. |

### 2.2 `lead_desk_tasks` (migration A)

| Column | Notes |
|---|---|
| `id` uuid, `tenant_id`, `lead_id` | `(tenant_id, lead_id)` references the lead. |
| `owner_person_id` | Who must do it. It follows the lead's owner on reassignment, with a `task` event. |
| `created_by_person_id`, `command_id` | Unique `(tenant_id, command_id)`: idempotency. |
| `kind` | `call_back`, `whatsapp`, `email`, `send_file`, `meeting`, `other`. |
| `title` | Made from the kind and the lead ("Call back Asha"); the seller may change it. |
| `note` | Up to 1,000 characters. |
| `starts_at`, `ends_at` | `starts_at` is the due time. `ends_at` is set only for meetings. Calendar-friendly. |
| `location` | Meetings: a place name or a link. |
| `status` | `open`, `done`, `cancelled`. |
| `done_at`, `done_by_person_id` | Set when done. |
| `original_due_at`, `snoozes`, `rollovers` | How far a task moved: for honesty in the ranker and reports. |
| `source`, `source_event_id` | `seller`, `after_call`, `note`, `message`, `commitment`, `report`, `meeting`, `adopted` (from `next_action`), `rule`. |
| `remind_before` | Minutes. A default per kind (2.4); the seller may change it. |
| `calendar_uid`, `revision` | `revision` rises with every change; a calendar uses it as `SEQUENCE`. |
| `client_at` | When the last change was made on the device (offline rules, section 3). |
| `created_at`, `updated_at` | |

Indexes:
- `(tenant_id, owner_person_id, starts_at) WHERE status = 'open'`: Tasks and reminders.
- `(tenant_id, lead_id, status)`: the lead page.
- `(tenant_id, updated_at)`: calendar sync.

### 2.3 `lead_desk_task_reminders`, the reminder ledger (migration A)

`(task_id, kind, for_due_at)` is unique, with `kind` one of `before`, `due` and `overdue`.
The sender claims a reminder with `INSERT ... ON CONFLICT DO NOTHING RETURNING`, so two
workers never send the same one. Other columns: `channel_mask` (push, inbox), `sent_at`,
`deferred_to` (quiet hours) and `tenant_id`. The in-app inbox reads this ledger, so push and
the inbox show the same reminders.

### 2.4 Defaults per kind

| Kind | Remind before | When no time is given | Doing it from its row |
|---|---|---|---|
| Call back | 5 min | In 1 hour | Places the call |
| WhatsApp | 0 | In 1 hour | Opens WhatsApp with the note as the message |
| Email | 0 | Today 17:00 | Opens mail with the subject |
| Send brochure/file | 0 | In 1 hour | Opens the share sheet |
| Meeting | 120 min if in person, 30 min if online | Has none (asks) | Opens the link or maps |
| Other | 0 | Tomorrow 10:00 | Opens the lead |

### 2.5 `next_action`, backward compatible

- On every task change, the writer sets `Lead.next_action_at` to the earliest open task
  owned by the lead's owner, and `next_action_note` to its title. With no open task, both
  are null.
- Old leads: an **adopter** job turns each `next_action_at` that has no open task into one
  `adopted` task. It does this once (a unique `source_event_id` per lead adoption), in
  batches, as app code (the migration gate forbids raw SQL in migrations).
- A past due that already alerted (`alerted_due_at = next_action_at`) is recorded in the
  ledger as sent, so it never alerts twice.
- The lead's existing outcome sheet, which sets the next call, writes a `call_back` task
  through the same writer.

### 2.6 Search (migration B, if allowed)

- `pg_trgm` (a trusted extension since PostgreSQL 13) with trigram GIN indexes on
  `lead_desk_leads.name`, `lead_desk_tasks.title` and `note`, and
  `(data->>'note') WHERE kind = 'note'` on events.
- Until it ships, search uses ILIKE over the same fields plus phone digits.
- Devanagari and Roman spellings of the same word don't match each other in this version.
  Transliteration is a later step.

## 3. Writes: the task writer

`lead_desk/tasks.py` holds `TaskBook` with `create`, `reschedule`, `snooze`, `done`,
`undo`, `cancel`, `reassign` and `adopt`.
- Each runs in the caller's transaction, locks the task row, writes the row and **one**
  `task` event with v1 keys: `action`, `task_id`, `kind`, `due_at`, `from_due_at`, `title`,
  `source`, `commitment` and `client_at`.
- It then sets the lead's `next_action` projection.
- A task done by its natural action is completed by that action's own command: "Call
  Asha" completes the call back when the call's outcome is saved, and a sent WhatsApp
  completes the WhatsApp task. The task event and the call or message event share the
  command id's family (`command_id` plus a suffix), so a replay does neither twice.

**Offline and conflicts.** Each change carries `client_at` and the `revision` it saw. A
change made on an older revision is merged by these rules, not refused:
1. Same `command_id`: nothing new; the current state is answered.
2. `done` versus `reschedule`/`snooze`: the change with the later `client_at` wins. The
   other is kept in the history as `superseded`.
3. `cancel` wins over everything except a later `undo`.
4. Two reschedules: the later `client_at` wins.
5. A note edit: the later `client_at` wins; the earlier text stays in the event history.
6. A `client_at` in the future (clock skew) is clamped to the server's `now`.

The web and the Android app already queue lead-desk writes durably (the builder's
`sync/write-queue.ts`, 41b2e08d, owner P0): a write is stored on the phone before it is
sent and retried until the server confirms, and a kept write answers `LeadsError.kept`.
Task commands go through the same queue. The server's idempotency makes every retry
safe, and a sheet treats a kept write as saved ("Saved on this phone, sending…").

## 4. Commitment extraction: rules first

Input:
- the outcome note after a call;
- a typed note;
- a WhatsApp message the seller sends or receives;
- a call Report's next steps, when AI is on.

Output: zero or more **proposals** `{kind, starts_at, ends_at?, location?, title,
confidence, evidence (the span), source_event_id}`, stored as a `suggestion` event and shown
for one-tap confirm or dismiss.

Pipeline (pure, `lead_desk/commitments.py`):
1. **Normalise.** Lowercase; Devanagari digits to ASCII; unify "5.30", "5:30" and "530";
   strip punctuation.
2. **Kind cues**, a lexicon per language:
   - **Call back:** "call back", "call me", "phone karo", "call karna", "फोन करा", "कॉल करा".
   - **WhatsApp:** "whatsapp", "wa", "व्हॉट्सअ‍ॅप", "msg karo".
   - **Email:** "email", "mail", "ईमेल".
   - **Send file:** "brochure", "pdf", "details bhejo", "पाठवा", "send".
   - **Meeting:** "meeting", "visit", "demo", "site visit", "भेट", "मीटिंग".
3. **Time grammar:**
   - clock times;
   - day words: "today", "aaj", "आज", "tomorrow", "kal" (read as tomorrow in a promise),
     "udya", "उद्या", "parso", "परवा";
   - weekdays in all three languages;
   - parts of the day: "morning", "subah", "सकाळी" → 10:00; "afternoon", "dopahar",
     "दुपारी" → 14:00; "evening", "shaam", "संध्याकाळी" → 18:00; "night", "raat",
     "रात्री" → 20:00;
   - relative times: "in 2 hours", "2 ghante baad", "after 2 days", "next week".
4. **Resolve against the event's time in IST:**
   - an hour from 1 to 7 without am/pm means pm; from 8 to 11, am unless "night" is said;
   - a time already past today means tomorrow;
   - a weekday means its next date;
   - a time outside the seller's work hours stays (a promise is a promise) but is marked
     "outside work hours".
5. **Location:** words after "at", "in", "-la", "-madhe" or "मध्ये" up to the time phrase
   ("at Baner office").
6. **Deduplicate:** proposals of the same kind within 30 minutes of each other are one;
   the rules' proposal and the Report's proposal merge, and the higher confidence wins.

A proposal never becomes a task without a tap. Dismissing one records it, so the same span
is not proposed again.

## 5. Scheduler and reminders (`lead_desk/scheduler.py`, pure planner plus a sender loop)

Each due of an open task reminds **once** (orchestrator, 24 Oct 2026: "a promise at 5:30
makes a reminder at 5:25, overdue at 5:31, one notification only"):
- `before` at `starts_at - remind_before` when the kind has a lead time (a call back, a
  meeting);
- else `due` at `starts_at`;
- `overdue` when quiet hours push the reminder past the due (it is sent at the start of
  work, saying it is overdue).

Rules:
- **Snooze** moves `starts_at` (by 15 min, 1 h, this evening or tomorrow), records
  `original_due_at` and re-plans. The ledger keys on `for_due_at`, so each due reminds once.
- **Quiet hours:** a reminder that falls outside the seller's work hours is deferred to the
  next start of work (`deferred_to`). A meeting inside quiet hours still reminds; its time
  was agreed.
- **Overdue** shows from `starts_at + 1 min` in every window (rows, the board, Tasks, My
  work), with no extra push. A missed due is visible, not nagged.
- **Rollover:** at the seller's day start, yesterday's open overdue tasks show in Today as
  "from yesterday" (`rollovers + 1`, one `rolled_over` event each). They are never copied.
- **Escalation (per business, off by default):** a task more than N hours overdue appears
  in the manager's digest. It is a count, not a push to the manager.
- **The sender** runs in the existing push loop: claim (ledger insert), group by seller
  ("3 tasks due now"), send through `push.py`. Nothing older than 2 hours is sent, as today.
- **Calendar:** `GET /v1/lead-desk/tasks/feed?updated_since=` gives the sign-in session's
  Google Calendar sync calendar-shaped items (`uid = task id`, `sequence = revision`,
  start, end, location, title, a description linking the lead). A cancelled or done task
  says so, and the event is removed.

## 6. The next best action (`lead_desk/next_best.py`, pure)

Candidates for a seller:
- open tasks that are overdue or due within 2 hours;
- promised call-backs (`source = commitment`);
- hot leads gone quiet (stage at or past "qualified", with the last contact older than the
  stage's `rot_hours`);
- new leads near or past the first-response target (`sla.py`);
- callers who weren't reached (the Call back list).

Score = Σ wᵢ · fᵢ, each fᵢ between 0 and 1, each with its words:

| Factor | f | Words |
|---|---|---|
| Overdue | min(1, minutes overdue / 120) | "20 min overdue" |
| A promise | 1 if from a commitment | "promised a 5:30 call" |
| Due soon | 1 − minutes to due / 120, within 2 h | "due in 15 min" |
| Missed caller | 1 | "called you, not reached" |
| SLA | lead age / first-response target, capped at 1 | "new lead, 25 min waiting" |
| Hot and quiet | min(1, (hours since contact / rot_hours) − 1) | "Interested, quiet 3 days" |
| Stage weight | milestone rank / max rank | "Meeting booked" |
| Just talked | −1 if contacted in the last 30 min | (pushes down) |

- Default weights: overdue 3, promise 3, missed caller 2.5, due soon 2, SLA 2, hot and
  quiet 1.5, stage 1, just talked 2.
- Weights are a per-business setting (Admin), bounded from 0 to 5.
- Ties go to the earlier due, then the lead id, so the order is deterministic.
- The output is the top N, with the two largest factors as the "because" line.

## 7. Retrieval

- **The lead:**
  - `LeadDetail` gains `recent` (the last 3 work events: calls, outcomes, notes, messages,
    stage moves, tasks) and `next_task` (the earliest open task);
  - the timeline shows each WhatsApp and email message as its own line beside calls and
    notes.
- **Across leads:**
  - **My work** is built (`GET /activity`, 2fb7d455);
  - **Notes:** `GET /notes?day=` lists the seller's notes, newest first, each linking to its
    lead;
  - **Tasks:** `GET /tasks?view=overdue|today|upcoming`;
  - **Search:** `GET /search?q=` covers leads, notes and tasks (section 2.6).
- **Home, "Recently called":** the last 40 leads the seller called, from `call` and
  `result` events (the actor index).
- **New list filters:** recently noted (a `note` event in 7 days), has an open task, and
  overdue (an open task past due). These join the sort and filters already on
  `GET /leads` (2fb7d455).

## 8. API (all under `/v1/lead-desk`, additive)

- `POST /leads/{id}/tasks` creates a task: `command_id`, `kind`, `starts_at`, `ends_at`,
  `location`, `note`, `title`, `client_at`, `source`, `suggestion_ref`.
- `PATCH /tasks/{id}` changes one: `command_id`, `revision`, `client_at`, and any of
  `starts_at`, `ends_at`, `location`, `note`, `title`, `kind`.
- `POST /tasks/{id}/done|undo|snooze|cancel`, each with `command_id`, `revision`,
  `client_at` (and `minutes` or `until` for a snooze).
- `GET /tasks?view=overdue|today|upcoming&person=` and `GET /tasks/feed?updated_since=`.
- `POST /suggestions/{event_id}/accept` (with the seller's edits) and `/dismiss`.
- `GET /next-best?limit=` returns the ranked list with its "because" words.
- `GET /notes?day=` and `GET /search?q=`.

## 9. Migrations (numbers from Align 3; 0129 is L5's)

- **A:**
  - creates `lead_desk_tasks` and `lead_desk_task_reminders`;
  - the event kind check gains `task` and `email`;
  - `lead_desk_meetings` gains a nullable `task_id`;
  - the backup and restore parity bump.
  - It follows the gate: no raw SQL in `upgrade()`, CONCURRENTLY only for indexes on
    existing tables, and a history-guard `downgrade()`.
- **B (if the gate allows an extension):** `pg_trgm` and its trigram indexes on existing
  tables, CONCURRENTLY.

## 10. Acceptance list: the seller's 22 (pytest on PostgreSQL unless marked)

1. "Call back at 5:30" in an after-call note at 16:10 proposes a Call back today at 17:30.
   One tap makes it. One push comes at 17:25; it shows overdue from 17:31; nothing else
   for that due.
2. "Call tomorrow evening" typed at 21:00 proposes tomorrow at 18:00.
3. "उद्या सकाळी 11 वाजता फोन करा" proposes a Call back tomorrow at 11:00. (unit)
4. "kal shaam 6 baje whatsapp bhejna" proposes a WhatsApp task tomorrow at 18:00. (unit)
5. "Meeting Thursday 4pm at Baner office" proposes a Meeting on Thursday, 16:00–17:00, at
   "Baner office", with reminders 2 hours and 30 minutes before.
6. "Send brochure" with no time proposes Send file in 1 hour.
7. Nothing is created without a tap. A dismissed proposal stays dismissed for that note.
8. Doing a WhatsApp task from its row opens WhatsApp pre-filled. Sending writes one
   `message` and one `task done` event.
9. Snooze 15 min twice, then done: the history keeps both snoozes, each new due reminds once,
   and no due reminds twice.
10. A task due at 22:30 for a seller who works 10:00–19:00 reminds at 10:00 the next day and
    shows overdue from 22:31.
11. Three tasks overdue from yesterday show in Today at the day's start as "from
    yesterday": one event each, no copies.
12. A note and a task made offline on the phone sync once. Sending the same commands again
    creates nothing new.
13. Offline conflict: done on the phone at 15:00 (sent at 15:10), rescheduled on the
    computer at 15:05. The later `client_at` wins, and the other stays in the history as
    superseded.
14. A reinstalled app shows the tasks and notes from the server and replays no old command.
15. The lead's next action is its earliest open task. Finishing that task moves the next
    action to the following task, or clears it.
16. Old leads with a `next_action_at` each become one open task, once. A due that already
    alerted doesn't alert again.
17. An overdue promised call outranks an Interested lead quiet for 3 days, which outranks a
    WhatsApp task due tomorrow. Each says why. (unit)
18. Search: "brochur pune" finds the lead whose note says "Send brochure, Pune office", and
    "9876" finds a lead by its phone.
19. The lead shows its last 3 actions and its next task.
20. Two sellers each see only their own tasks, reminders and My work, while the manager
    sees the team's. Reassigning a lead moves its open tasks to the new owner, with a
    history line.
21. Calendar: a changed task keeps its `uid` and raises its `sequence`; a cancelled task is
    marked cancelled.
22. Deleting a lead removes its tasks and reminders. The deletion counts them, and the
    audit trail keeps the counts, not the words.

**Beyond the list:**
- Property tests:
  - the planner: any chain of snoozes and reschedules gives at most one reminder per
    (task, kind, due);
  - overdue never stops while a task is open;
  - the time parser never returns a past time for a promise;
  - the ranker: more overdue never ranks lower, all else equal.
- A PostgreSQL scale test: 400 leads × 2,000 events × 600 tasks, the Tasks views and
  search within a time budget.
- Two sender workers claim the same due: one push.
- A simulation: 5 sellers over 14 days, with seeded calls, notes with promises, snoozes,
  offline duplicates and reassignments. No lost task (every confirmed proposal has one), no
  duplicate task per command, at most one reminder per (task, kind, due), and the overdue
  counts match.
- On a phone, end to end: call → outcome note with "call back 5:30" → confirm → the
  reminder (fake clock) → done.

## 11. What the seller sees (the windows), from the owner's and the tester's words

- **Lead page:**
  - the last 3 actions and the next task under the header;
  - one action row: Call, WhatsApp, Email, Note, Remind;
  - a proposal card after a call or under a note ("Call back today 5:30? Set · Change ·
    No").
- **Tasks tab:** Overdue, Today, Upcoming. Each row has the lead, the type, the time, and
  one-tap Call or WhatsApp. Done in one tap; doing a WhatsApp or Email task opens it
  pre-filled.
- **My work** (built): calls, notes and moves, today, yesterday or this week. **Notes**:
  all the seller's notes, newest first.
- **Home:** "Recently called" (the last 40), and the next best action list.
- **All leads:**
  - the total ("383 leads") and continuous loading as she scrolls (built);
  - compact cards on phones by default, the table one tap away (built);
  - columns sized to their content, a column chooser that hides low-value columns, owners
    as "Swamini D.", names wrapping to 2 lines;
  - a call-state column (Not called / Called · outcome / Couldn't reach) with a filter;
  - filters for recently contacted, recently noted, recently added, has an open task and
    overdue;
  - saved views as chips, named from their filters, renamed inline.
- **"+ Lead":** one button opening a small sheet, separate from search. A number that
  already exists says so, with "Open that lead" (`/leads/match`).

## 12. Phasing

- **v0.88: the engine core and the smallest windows onto it.** (Also already built or in
  test for v0.88: server sort and filters, My work, the phone table, continuous loading.)
  - Migration A, the task writer and the adopter.
  - Rule-based extraction (English, Hinglish, Marathi).
  - The planner and sender, with quiet hours and rollover.
  - Acceptance tests 1–16 and 19–22.
  - Screens: on the lead page, the next task, a one-tap "Remind", and proposals to confirm
    after a call and under a note. A Tasks tab (Overdue, Today, Upcoming).
  - Already built for v0.88: server sort and filters, My work, the phone table.
- **v0.89:**
  - the next best action, with tunable weights (acceptance 17);
  - search with trigram (acceptance 18, migration B);
  - the calendar feed for the sign-in session's Google Calendar;
  - the Notes view and Home's "Recently called";
  - saved views as chips, with names made from the filters;
  - the All leads table: continuous loading, column widths, the call-state column, and
    compact cards on phones by default;
  - email logging;
  - AI Report proposals merged into extraction.
