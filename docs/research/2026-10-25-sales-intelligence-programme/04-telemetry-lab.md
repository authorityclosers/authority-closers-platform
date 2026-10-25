# 04 — The measurement loop: from research questions to telemetry

*Programme chapter 4 (Part B of the 25 Oct 2026 order). The build itself is documented in
`docs/product/telemetry-friction-lab.md`; this chapter says how it answers the research.*

## What was built

The friction lab (workbench commit a59b98312) adds to the existing product telemetry:

- **Flows** (`sx.flow`): first-run setup, phone setup, Add lead (sheet and quick add) and
  "How did it go?": where each run starts, the steps it reaches, refused Saves, and how it
  ends (done, skipped, cancelled, left half way, failed, or no end seen).
- **Permission prompts** (`sx.permission_prompt`): each Android ask in phone setup, granted,
  denied, blocked or a settings screen that didn't open, with the answer time.
- **Dwell that means attention**: the time a screen was on view (`seen_ms`), not the time a
  call spent in the dialler; the screen the app went to the background or closed on.
- **Where people tap in vain**: rage and dead taps with the screen zone and the element's
  code name.
- **Loops, quick backs and workspace switching**, worked out from screen views and the
  workspace each event was recorded in.
- **A weekly report** in Admin (→ Product telemetry → Friction) and as markdown each Monday
  07:00 IST, ranking findings by people affected × severity, each with evidence, a suggested
  owner and the question for the builder. Fewer than three people never make a finding.

## How it maps to the research

| Research question (chapter) | Telemetry that answers it | Where it shows |
|---|---|---|
| Is logging a result a habit, done in seconds? (ch 2 §1, §6.3; ch 3 journey c) | `log_result`: finished share, time to finish, where people stop, refused Saves | Friction → Flows |
| Do sellers get through phone setup? Which permissions do they refuse, on which phones? (ch 1 rec 1–2; ch 3 rec 14) | `phone_setup` flow; `permission_prompt` outcomes; the phone's permission snapshot | Friction → Prompts; Devices |
| Does first-run setup lose people, and where? (owner programme item 4) | `onboarding` flow by path (business, solo, join) | Friction → Flows |
| Are people confused by organisation and account switching? (owner programme item 4) | bounces, ping-pong, switches within a minute of opening, menu opened without a switch | Friction → Workspace switching |
| Where do people tap and nothing happens? (owner programme item 6) | dead and rage taps by element and zone; key taps with no change for a second | Friction → findings, Screens |
| Which screens do people bounce off or go back and forth between? (ch 3 §6.3) | quick backs, loops, exits, seen time | Friction → Screens |
| Are budget phones fast enough? (ch 2 rec 14; ch 3 §7.2) | tap-to-response by device tier, Web Vitals | Overview, Devices, release gate |
| Do nudges help or annoy? (ch 2 §4, rec 15) | to add with the drift nudge: delivered, dismissed, "on a break", time back to the next call, channel turned off | (next, with Lead OS) |

## Still to wire (follow the same contract)

- "How did it go?" lines in `leads/lead-sheet.tsx`: ready as a small patch, held until
  another session's open edits in that file are committed.
- The seven benchmark journeys of chapter 3 that aren't flows yet: take leads (the "taking
  new leads" switch), call a lead, add a note, set a reminder, send a WhatsApp template,
  review a report (report reads already exist).
- Drift-nudge outcomes, when the team engine's nudges ship.
- In-app micro-surveys (SEQ after a flow, one-tap reason after abandoning), with frequency
  caps (ch 3 §8.1).

## How to read it (limits)

- At tens of testers, week-on-week changes are signals, not proof; chapter 3 §8.7 gives the
  numbers needed for firm comparisons. Pair every finding with a "why" from the monthly
  think-aloud round.
- The report sees the web pages only (including the Android app's pages), not the native
  Android screens.
- Telemetry is disposable analytics: never progress, scoring or access state (AGENTS.md).
