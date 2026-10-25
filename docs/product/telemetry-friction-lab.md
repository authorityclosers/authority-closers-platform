# Telemetry friction lab: where people get stuck (25 Oct 2026)

Owner order, 25 Oct 2026 (programme item 6): "Automatically find where users stop, which
screen they get stuck on, where they try to tap (dead or rage taps), and why. Collect data at
scale from many testers. Build the pipeline: capture, aggregate, auto-analyse, and a weekly
report feeding the redesign loop."

This builds on the product telemetry already in place (option B consent, notice v2, Admin
→ Product telemetry, the improvement loop in `telemetry-improvement-loop.md`). Nothing here
needs a migration: the report is worked out from `analytics_events` (retention policy
`sx-product-analytics-v1`, 180 days) whenever it is asked for, so a past week always reads
the same.

## 1. What is captured (web app and the Android app's pages)

Counts, timings and code names only. No text, names, numbers, ids or call content.

| Signal | Event | What it carries |
|---|---|---|
| Dwell per screen | `sx.screen_viewed` gains `seen_ms`: the time the previous screen was **on view** (a call in the dialler does not count), beside the old wall-clock `stay_ms` | screen, from, nav, stay_ms, seen_ms |
| Leaving the app | `sx.screen_hidden` (new): `background` when the page goes out of view (at most once in 30 s), `exit` when the page closes, with the screen's total `seen_ms` | screen, kind, seen_ms |
| Dead and rage taps | `sx.tap_issue` gains `zone` (the viewport in 4 rows × 3 columns, `r1c1` top left), `element` (the element's `data-sx-feature` / `data-sx-action`, else its CSS-module style name such as `leads-table.stagechip`) and `where` (a fingerprint of its place on the page) | kind, target, action, screen, zone, element, where |
| Back-and-forth loops | worked out from `sx.screen_viewed` (A, B, A, B within 2 min in one visit) | – |
| Quick backs | worked out: a screen left with Back within 5 s of arriving | – |
| Abandoned flows | `sx.flow` (new) for first-run setup, phone setup, Add lead (sheet and quick add) and "How did it go?" | flow, outcome, step, via, index, steps, left, ms |
| Permission prompts | `sx.permission_prompt` (new), one per ask in phone setup | permission, outcome, via, from, ms |
| Workspace switching | worked out from the workspace each event was recorded in, plus `sx.feature_used` `workspace_menu` when the switcher opens | – |

`/welcome` (first-run setup) is now a route template and the screen `welcome`; the setup page
sets the telemetry session itself (it has no app frame).

The notice (v2) already covers these: screens and how long, taps and how fast the app
answers, which of the app's permissions are on. No new notice version is needed.

### The flow contract (for builders)

`apps/sales-xray-web/app/telemetry-flows.ts`:

```ts
const flow = useFlow("onboarding", { active: ready, via: path });
flow.step("name", 1, 5);      // a new step on view (repeats are ignored)
flow.blocked("name");         // Continue or Save refused for something missing
flow.done({ left: 2 });       // or flow.skip(), flow.cancel(), flow.fail()
```

- A run starts when `active` turns true or at its first `step()`. After it ends, the next
  `step()` starts a new run (quick add: one run per lead).
- Unmounting with a run still going, or the page going away, sends `abandon`. A run with no
  end at all (the app was killed) shows in the report as "no end seen".
- Flows, steps and ways in are a fixed list on both sides (`FLOWS`, `FLOW_STEPS`,
  `FLOW_VIAS` in `telemetry/sales_xray.py`; the types in `telemetry.ts`). A new flow or step
  is added in both, with a test.

Where it is wired today (keep these lines when redesigning the screens):

| Flow | File | Start | Steps | Ends |
|---|---|---|---|---|
| `onboarding` | `welcome/setup-flow.tsx` | first step | start, name, business, team, first | done (Go to Home / first action), skip (Skip setup), blocked on a bad name or address |
| `phone_setup` | `leads/phone-setup-flow.tsx` | first step | calls … recorder (`callLog` as `call_log`) | done with `left`, cancel on close |
| `add_lead` | `leads/capture-dialogs.tsx` (via `sheet`), `leads/quick-add.tsx` (via `quick`) | sheet open / first typing | form, duplicate | done on add, cancel on close or Escape, blocked on an empty form or a duplicate |
| `log_result` | `leads/lead-sheet.tsx` `CallOutcome` (via `after_call` or `lead`) | back from a call, or first answer | talk, reason, stage | done on save, blocked when Save is refused |

Permission prompts: `leads/phone-setup-telemetry.ts` reads the phone's setup status before
and after each ask: `granted` (the phone now says done), `denied`, `blocked` (Android no
longer asks; only the app's settings can allow it), `not_opened` (a settings screen that
didn't open). `via` is `prompt` or `settings`; `from` is `setup` or `fix` (one Fix from
Settings).

Tap element names come from code: add `data-sx-feature="snake_case_name"` to anything people
should be able to find in the report by name. Never put words, names or ids in it.

## 2. The weekly analysis

`packages/python/ac_platform/telemetry/friction.py`, one India week (Monday 00:00 IST to the
next Monday) against the week before:

- **Screens**: views, people, seen time (median and 90th percentile), quick-back share, exit
  share (the last screen of a visit), rage and dead taps per 100 views, key taps that changed
  nothing for a second, loops. Sorted by weighted friction per 100 views (rage 3, dead or
  unanswered tap 2, quick back and loop 1).
- **Flows**: started, finished, skipped, cancelled, left half way, no end seen, failed;
  how many reach each step, where they stop, refused Saves, time to finish.
- **Permission prompts**: asked, granted, denied, blocked, didn't open, answer time.
- **Workspace switching**: people in several workspaces, switches, bounces (straight back
  within 2 minutes), ping-pong (3 switches in 10 minutes), switches within a minute of
  opening, switcher opened without a switch.
- **Findings**, each with a stable key, evidence, the people affected the week before, a
  suggested owner and the question for the builder:

| Kind | Bar (≥3 people always) | Severity |
|---|---|---|
| `flow_quit` | people stopping at a step | 4 for setup and logging a result, else 3 |
| `rage_tap` | per screen and element | 3 |
| `permission` | refused or blocked ≥25% of ≥4 answers | 3 for calls, recordings, call history; else 2 |
| `workspace_bounce` | bounces; switches within a minute of opening | 3; 2 |
| `dead_tap` | per screen and element | 2 |
| `unresponsive` | key taps with no change for a second | 2 |
| `quick_back` | ≥25% of ≥10 views | 2 |
| `loop` | per screen pair | 2 |
| `flow_blocked` | Save refused at a step | 2 |
| `error_shown` | per surface and code | 2 |

Rank = people × severity. Privacy: any count of people under three is shown as `<3`, and
nothing under three people becomes a finding.

## 3. Where it shows

- **Admin → Product telemetry → Friction** (`/telemetry/friction?week=YYYY-MM-DD`): this week
  so far and the five before, with "Download this week as markdown". Fixture:
  `/review-fixture/telemetry-friction` (`?state=empty`).
- **API**: `GET /v1/admin/telemetry/friction[?week=][&format=markdown]`, control accounts in
  the operations workspace, and staff keys with `admin:read` (builders and agents read it with
  `ac-admin`).
- **The weekly job** (`infra/application/scripts/ac-telemetry-friction`,
  `ac-telemetry-friction@<env>.timer`, Mondays 07:00 IST): runs
  `python -m ac_platform.telemetry.friction_cli` inside the environment in a read-only
  transaction and writes
  - `/var/lib/ac-telemetry-friction/<env>/<week>.md` (kept), and
  - `/home/acdev/reports/telemetry-friction/<env>/<week>.md` and `latest.md` for the
    builders.
  Before a release carries the module it does nothing.

## 4. How it feeds the redesign loop

1. Monday 07:00 IST: the report for the week that ended is written; Admin shows it.
2. The orchestrator or the builder takes the top findings into the redesign plan (Copy task
   gives the card text). Each finding names its screen, element and the question to answer.
3. The fix ships; the next Monday's report shows the finding's people against the week
   before, or lists it under "Gone since the week before".
4. Quarterly, the usability benchmark (research programme chapter 3) checks the same journeys
   with real sellers, so telemetry and observed behaviour are read together.

## 5. Limits

- Only what the web pages see. Native screens of the Android app (outside the WebView) send
  only the phone events of `telemetry-android-bridge-20261024.md`.
- "No end seen" can't tell a killed app from a phone that went idle on the step.
- Dead-tap detection needs the element to look tappable (pointer cursor) or to be named;
  phones have no hover, so most dead taps come from styled elements.
- Workspace switches read from recorded events: a switch with nothing recorded either side
  is not seen.
- The tester base is small (tens): read week-on-week changes as signals, not proof. The
  research programme's chapter 3 gives the sample sizes needed for firm comparisons.
