# Dev sandbox live feed

The dev workspace **AC Sales Sandbox** (`3100ddbc-4549-4a5e-85b8-421af6edd588`, dev-live) gets
new fictional sales work every working day, so every screen the owner is redesigning shows
real-looking numbers. The owner asked for it on 15 Nov 2026 at about 01:45 IST: "a fresh data
server, a sandbox, e.g. AC Sales Sandbox, where data keeps coming live every day in proper
working hours, so we can test and see how things look".

**Dev only.** `feed.py` refuses unless `AC_ENVIRONMENT=development` and the workspace is the
flagged sandbox named "AC Sales Sandbox". It never touches staging or production.

## What it does

The feed writes through the app's own lead desk (`LeadDesk`, `TaskBook`) as each person. That
is the same code the routes call. It reuses the generator that first built the sandbox,
`scripts/data-changes/sandbox-organisations.py`.

Each tick does the following:

- **New enquiries.** 14 to 24 Inbound enquiries arrive a day, at any hour, mostly in the
  evening. They come from Meta, Google, the website and YouTube, and the team's rules give
  them out. The day's plan is fixed, so every tick takes its own slice of it.
- **Cold lists.** When a Cold seller has fewer than 60 untouched leads, the coach uploads a
  fresh Cold list of 150, shared among the sellers running low.
- **Calls.** Sellers dial what the app's queue puts first: follow-ups due, then new
  enquiries, then retries, then Cold up to each seller's daily cap. The phone logs each call
  with its real start and seconds. About a third connect.
- **After the call.** The seller answers the after-call sheet with an outcome and reason. A
  call can lead to a follow-up, a call-back or WhatsApp task, a meeting (booked, then held,
  missed or cancelled), a win, a loss or junk. Now and then the seller writes a note.
- **Support calls.** One to three times a day, a customer who already bought rings their
  seller with a question. That's a call that isn't a sale, with a note saying so.
- **Daily tidy-up.** Each seller closes up to 8 Not Connected leads that have been stale for
  a week as Lost (no response).
- **The owner closes.** At about noon each day, the coach hands the owner one or two hot
  leads (Meeting Done or Interested), never more than 8 open at once. The owner works only
  those, late and slowly, so his own "Me" view has calls, tasks and follow-ups. His own
  photo is never replaced.

Sellers differ, so the rows don't look alike:

| Seller | Style |
|---|---|
| Priya Deshmukh | The star: fastest, connects most, never idle |
| Farah Shaikh | Leaves most due follow-ups for another day, so her tasks go overdue |
| Sneha Iyer | Inbound only |
| Aditya Joshi | Cold only |
| Rohan Patil | Steady |
| Venkatesh Ramakrishnan | Added 15 Nov; a long name, so the screens show how they cut names |

One seller a day doesn't work, in turn, and never the star. Each seller has a drawn portrait
as their profile photo (`avatars.py`, flat illustrations made with Pillow, never a real
person).

Nothing writes a count. Every number on a screen is the app counting what it stored, so
Connected is never more than Attempted, talk time is the calls' seconds, and today's counts
match the lists. The honest-numbers rules hold: a call is a phone-logged event, and connected
means the phone logged seconds.

## Its state

Each run is one transaction. The moment the run played up to, its cursor, is an audit event
(`lead_desk.sandbox_feed`) in the same transaction. A crash replays nothing, and a late tick
catches up (at most two days; older gaps are `backfill`'s job).

Working hours are every day from 09:30 to 19:30 with a lunch break. They're set on the
workspace, because the app only logs phone calls inside work hours.

## Rolling window

Leads closed more than 45 days ago, and leads typed in by hand (testers' and the QA robot's),
move to History. That's `lead_desk_leads.pipeline = "history"`: kept and counted in Analytics,
but out of every work list. Nothing is deleted.

## Running it on ac

`infra/application/development/sandbox-feed/install-sandbox-feed.sh` installs the feed (dry
run by default; `--apply`, `--remove`):

- `ac-dev-sandbox-feed.timer` runs `ac-dev-sandbox-feed.service` every 12 minutes, with up to
  2.5 minutes of jitter, from 09:30 to about 20:20 IST. The service runs one `tick --apply`.
- The service runs as uid 10001 (the dev-live API's user) with the API's env and interpreter,
  inside `ac-strikes.slice`, at nice 15 with idle IO. It logs to journald:
  `journalctl -t ac-dev-sandbox-feed`.
- For one-off runs, use `sudo ac-dev-sandbox-feed <command> [--apply]`. It's dry run unless
  you pass `--apply`.

| Command | What it does |
|---|---|
| `setup` | Adds the sixth seller, sets the work hours, draws the avatars, moves typed-in leads to History |
| `tick` | Plays from the cursor to now minus 20 minutes (what the timer runs) |
| `backfill --from=YYYY-MM-DD` | Plays whole days up to the last midnight, each in its own transaction |
| `night --pace=N` | One-off: plays today from 00:00 to now, N times faster, with the hours open all day inside that transaction only |
| `read` | Shows today's counts per seller, read-only |

Each tick takes about 3 seconds of CPU. No paid AI is used.
