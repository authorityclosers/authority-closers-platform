# Team engine: lead distribution, targets, nudges and My day

Owner, 25 Oct 2026 (owner program, sections 1 and 2): an owner or manager assigns leads in bulk
and by rules and sets daily and weekly targets per seller. Progress comes from real activity. A
seller who drifts away gets a distinct sound that brings them back, with quiet hours respected. My
day ranks the work assigned to the seller; when today is empty, it shows the most useful recent
data, never a wall of zeros.

This document is the engine. The builder draws the screens on top of its API.

## 0. What already exists (not rebuilt)

- **Allocation of each new lead** (`lead_desk/allocation.py`). A lead goes to someone available
  and under their cap who speaks its language and covers its area and product. A returning lead
  goes back to its seller. Otherwise the fewest open leads wins, then whoever waited longest.
  Each decision has a reason in words.
- **Reassigning one lead or many** (`POST /leads/{id}/assign`, bulk actions on All leads), and the
  "Unassigned" scope.
- **Work memory** (`work-memory-engine.md`): tasks, the reminder ledger and the push loop
  (`push.collect`), and `next_best.rank`.

## 1. Distribution: assign a chosen set of leads by a rule

A manager picks leads (selected rows, a filter, or "all unassigned") and sellers, then a rule:

- **Even:** round-robin over the chosen sellers, in a stable order. Each lead goes to the seller
  with the fewest leads from this distribution so far; ties go to the seller's place in the
  order. At the end, any two sellers differ by at most one lead.
- **Balanced:** like Even, but counted on open leads after the move, so lighter sellers catch up.
- **By source / by city:** the manager maps each source or city to one or more sellers. Each
  group is spread Evenly over its sellers. A lead whose source or city has no mapping stays where
  it is, and the preview says so.
- **Caps:** a seller at their open-lead cap takes no more. Leftovers stay unassigned, and the
  preview says how many.
- **Who is left alone:** a closed lead (Won, Lost, Junk) never moves. A lead already with a
  chosen seller stays with them under Even unless the manager asks to "spread everything".

`POST /leads/distribute` takes `{command_id, lead_ids | unassigned, rule, sellers, groups,
spread_all, preview}` (owners and managers):
- `lead_ids` are the chosen rows; `unassigned: true` takes every open lead nobody holds, oldest
  first. `sellers` (Even, Balanced) defaults to every seller taking leads; `groups` (By source,
  By city) maps each source or city, in any case, to its sellers.
- The preview returns the plan: per seller, how many leads, their open leads after it and their
  cap; leftovers with why; the sources and cities among the open leads, with how many, so the
  screen can offer the map; no lead names.
- Apply moves each lead the way a manager's own move does, one history line each, reason
  "Distributed: <rule>". It is idempotent by command_id: a retry returns what it did.
- At most 1,000 leads per call; `more` says when more unassigned leads wait.

Pure core: `distribute(leads, sellers, rule) -> Plan`, with no database and no clock.

## 2. Targets: per seller, per day and week

A target is a seller, a period (day or week, India time, the week starting Monday), a metric and a
number. The metrics:

| Metric | Counted from |
|---|---|
| calls | `call` events by the seller (any direction the app logs), plus outcomes logged without a call event: one per call |
| connects | outcomes with `connected = true` |
| follow_ups | outcomes on a lead whose follow-up was due (as Home's "Follow-ups done" counts), plus tasks done |
| meetings | meetings booked (`meeting` events, action booked) |

- Targets are set by an owner or manager. A new value supersedes from that day; history keeps the
  old one (table `lead_desk_targets`: tenant, person, period, metric, value, effective_from,
  set_by, created_at).
- **Progress** for each metric is `done / target`.
- **Pace** is how much of the target should be done by now. For a day, the elapsed share of the
  seller's work hours (none before work starts, all after it ends). For a week, the elapsed share
  of the week's work days and hours.
- **Behind** means `done < target x pace - slack`, with slack = max(1, 10% of the target).
- A seller without targets has no progress and no drift nudges. Idle nudges still apply if the
  workspace turns them on.

Pure core: `progress(events, targets, hours, now) -> [MetricProgress]`.

## 3. Nudges: one push per window, never in quiet hours

Two kinds:
- **drift:** behind pace on any metric, checked from an hour into work.
- **idle:** no activity for 45 minutes inside work hours while the seller has due work (a due
  task, a lead to call now, or a new lead).

The rules:
- **Windows:** the work day is cut into 2-hour windows from the start of work. At most one nudge
  per seller per window, whatever its kind. The ledger (`lead_desk_nudges`: tenant, person, kind,
  window_start, sent_at; unique on person and window_start) is written before the push is sent,
  as with task reminders.
- **Quiet hours:** never outside the seller's work hours, never on a day off, never in the first 30
  minutes of work, and never within 10 minutes of their last call.
- **At most 3 nudges a day.** After a nudge, activity within 20 minutes counts as "back to work".
- **The push** (agreed with the Android app, 25 Oct 2026): FCM data
  `{type: "lead_desk", kind: "nudge", urgency: "urgent", tenant, count}`, with no lead id and no
  words; `count` is the work waiting. The app plays its own distinct sound and shows one line,
  read on the seller's own session from `GET /alert?kind=nudge`:
  `{title, body, url: "/leads", lead_id: null, urgency: "urgent"}`, for example "Behind pace" and
  "You're 6 calls behind today's pace." The sender (`nudge_push`) runs in the lead alerts' pass,
  under its lock, and looks at each seller at most every five minutes.
- **Off by default.** An owner or manager turns nudges on per workspace and off per seller with
  `PUT /nudges {expected_revision, enabled, off_for}`; the team settings show `nudges` and
  `nudges_off_for`.

Pure core: `nudge(progress, last_activity, due_work, hours, ledger, now) -> Nudge | None`.

## 4. My day: ranked work, and useful data when today is empty

`GET /my-day` (a seller, or a manager for a seller) returns:
- **do_now:** up to 10 items, ranked by `next_best.rank` over open tasks, leads due, new leads and
  missed calls. Each item has a lead id, what to do (call, WhatsApp, meeting), why in words, and
  when.
- **progress:** today's numbers against targets, when there are targets.
- **fallback**, only when do_now is empty and today's numbers are all zero, in this order:
  1. the next due work (tomorrow's tasks and calls);
  2. this week's real numbers, compared with last week's;
  3. the leads touched most recently ("Recently called").
  Never a list of zeros: a metric at zero is left out unless a target makes it meaningful.

Pure core: `my_day(candidates, numbers, targets, now) -> MyDay`.

## 5. Acceptance scenarios

1. **Distribution.** Even over 3 sellers for 10 unassigned leads gives 4, 3, 3. A rerun with the
   same command changes nothing.
2. **Caps.** Even with one seller at cap leaves that seller out, and the preview names the reason.
3. **By source.** Facebook leads to A and B, Google to C: the Facebook leads alternate between A and
   B, the Google leads all go to C, and leads from an unmapped source stay put and are counted.
4. **Closed leads.** Won, Lost and Junk leads never move, even when selected.
5. **Reasons and history.** Each move writes one history line with the reason "Distributed: Even".
   The preview contains no lead names.
6. **Targets supersede.** A target set at 30 and then 40 on the same day counts 40 from that day;
   the previous day still shows 30.
7. **Calls counted once.** A call with its outcome counts as one call; a missed call counts as a
   call and not as a connect.
8. **Pace.** With 50 calls a day over 10:00 to 19:00, at 14:30 the pace is 25, so 18 done is
   behind and 22 is not (slack 5).
9. **Week.** On Wednesday at 19:00, the end of work, a 200-call week has a pace of 100: three of
   its six work days (Monday to Saturday) are done.
10. **Drift nudge.** It fires once in a window and not again in that window, even after a snooze.
11. **No nudge** before work starts plus 30 minutes, after work ends, on a day off, or within 10
    minutes of a call.
12. **Idle nudge** only with due work. An idle seller with nothing due gets none.
13. **At most 3 nudges** in a day.
14. **Two senders:** two senders in the same pass send one nudge (ledger unique).
15. **My day order:** an overdue promise before a new lead, and a new lead before a cold lead.
16. **Empty My day:** it shows tomorrow's first task and this week's numbers, never "0 calls,
    0 connected".
17. **A manager's view** of a seller's My day sees the seller's items, not their own.

## 6. Property tests (seeded random, like `test_scheduler`)

- **Distribution:**
  - every input lead is placed once or counted as left over;
  - no seller exceeds their cap;
  - under Even, max - min <= 1 among sellers under cap;
  - the plan is deterministic for the same input;
  - closed leads never appear in moves.
- **Progress:**
  - progress never decreases as events are added;
  - pace is 0 before work and 1 after it;
  - behind implies done < target.
- **Nudges, over random days of activity:**
  - at most one per window and three per day;
  - never outside work hours;
  - never within 10 minutes of a call;
  - none without targets or due work.
- **My day:**
  - do_now holds no closed lead;
  - it is sorted by rank;
  - the fallback appears only when do_now is empty and the numbers are zero.

## 7. Order of work

1. Pure modules and their property and unit tests: `distribute.py`, `targets.py`, `nudges.py`,
   `my_day.py`.
2. The migration (number from Align 3): `lead_desk_targets`, `lead_desk_nudges`.
3. The API: distribute (preview and apply), targets (read and set), `GET /my-day`, the nudge words,
   and nudges in the push pass. DB tests for scenarios 1 to 17.
4. The builder draws the screens: the Assign sheet, Targets in Team, My day on Home, and the nudge
   card. Android plays the nudge sound.
