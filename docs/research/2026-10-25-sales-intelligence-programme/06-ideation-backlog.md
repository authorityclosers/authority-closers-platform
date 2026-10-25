# 06 — Ideation backlog for v0.90–v0.92

*Programme chapter 6. 25 Oct 2026. The owner asked for "new ideation". These are 27 ideas,
each grounded in this programme's chapters, the friction telemetry (chapter 4) and the
phone findings of 24–25 Oct. Each has the problem, the evidence, the idea, impact and effort,
and the test that proves it worked. They are ranked; the owner's short list comes first.*

**Sources used for "what we saw":** the phone sweep on a Redmi 13 and a Note 8 Pro (Play
1.0.23, 24 Oct); the v0.89 screen matrix (420 states: 5 screens × 7 phone sizes × 4 text
sizes × light/dark, 25 Oct); the Lead OS phone pass (24 Oct); the owner's programme notes
(25 Oct). **Already in flight and therefore not repeated here:** Leads opening on "Now" with
one view switch, search as a field, the lead sheet on one grid, Home's zero states,
onboarding in one flow, the urgency alert system and haptics, the notifications screen, team
targets and nudges (engine), lead distribution, in-app updates. Several ideas below say how to
ship those well and how to measure them.

**How ideas are ranked.** Score = impact × confidence ÷ effort.
- Impact: H = 3 (the daily core loop, or a blocker), M = 2.
- Confidence: 3 = research evidence *and* our own observation; 2 = one of the two; 1 = a
  hunch.
- Effort: S = 1 (days, one owner), M = 2 (a release), L = 3.

Ties go to the core loop (take a lead → call → log → follow up).

---

## Short list for the owner (do these first)

1. **Unblock phone setup.** Fix the broken "Phone setup" tile (it closes and opens nothing:
   3 of 3 tries) and give Xiaomi Play users the recordings-folder grant. Today those users
   can't attach recordings at all (ideas 1 and 8).
2. **Make "How did it go?" fast and only after a real call.** It opens within a second of
   coming back from the dialler, answers are pre-chosen from the call's length, and four big
   one-tap outcomes replace the multi-step form (ideas 2, 5 and 9).
3. **Every tap answers at once.** A pressed state within 100 ms everywhere (today the first
   visible change comes about 0.25 s after the tap), plus a release gate on taps that change
   nothing and on the screen matrix (tiny text, cut words, small targets) (ideas 3 and 6).
4. **Speed-to-lead.** A first-call timer on every new lead and an urgent "new lead, call now"
   alert, reported as minutes to first call per seller and source (idea 4).
5. **Tester missions.** Five guided tasks inside the app for Play testers, with a one-tap
   "why did you stop?". This brings Alpha testers in and keeps them; the Play production gate
   needs 12 opted in for 14 days, and 1 is (ideas 7 and 13).
6. **Ship targets and nudges the way the evidence says.** A weekly target with a daily pace,
   a stretch tier and no red failure; a private, calm drift nudge with a break option, caps
   and a holdout group to prove it helps (ideas 11 and 12).

---

## The ranked backlog

| Rank | Idea | Impact | Conf. | Effort | Score | Release | Owner |
|---|---|---|---|---|---|---|---|
| 1 | Fix the Phone setup tile | H | 3 | S | 9 | v0.90 | builder |
| 2 | "How did it go?" only after a real call, open within 1 s | H | 3 | S | 9 | v0.90 | Lead OS |
| 3 | Pressed state on every tap; gate on "no change" | H | 3 | S | 9 | v0.90 | builder |
| 4 | Speed-to-lead timer and urgent new-lead alert | H | 3 | S | 9 | v0.90 | Lead OS |
| 5 | Pre-chosen answers from the call's length | H | 2 | S | 6 | v0.90 | Lead OS |
| 6 | The screen matrix as a release gate (text size safe) | M | 3 | S | 6 | v0.90 | builder, Align |
| 7 | Tester missions for Play Alpha | H | 2 | S | 6 | v0.90 | builder, orchestrator |
| 8 | Xiaomi recordings-folder grant in the Play build | H | 3 | M | 4.5 | v0.90 | Android |
| 9 | Four one-tap outcome tiles | H | 3 | M | 4.5 | v0.91 | Lead OS, builder |
| 10 | A daily notification budget and digests | H | 3 | M | 4.5 | v0.91 | builder, Android |
| 11 | Drift nudge v1 with a holdout and a kill switch | H | 3 | M | 4.5 | v0.90–0.91 | Lead OS |
| 12 | Target framing: pace ring, stretch tier, "carried to tomorrow" | H | 3 | M | 4.5 | v0.90–0.91 | Lead OS, builder |
| 13 | In-app ease question and "why did you stop?" | H | 3 | M | 4.5 | v0.91 | telemetry |
| 14 | "One thing to try" shown before the next call | H | 3 | M | 4.5 | v0.91 | Report |
| 15 | Permission explainer and blocked-permission rescue | M | 2 | S | 4 | v0.90 | Android, builder |
| 16 | Monday fresh-start card | M | 2 | S | 4 | v0.91 | builder |
| 17 | Workspace identity band and empty-workspace guard | M | 2 | S | 4 | v0.90 | builder |
| 18 | UI language in telemetry | M | 2 | S | 4 | v0.90 | telemetry |
| 19 | Bug reports carry the flow and step | M | 2 | S | 4 | v0.91 | bug reporter |
| 20 | Phone health per seller on the manager view | H | 2 | M | 3 | v0.91 | Android, Lead OS |
| 21 | "Next best lead" with its reason | H | 2 | M | 3 | v0.91 | Lead OS |
| 22 | Brief-first call report on the phone | H | 2 | M | 3 | v0.91 | Report |
| 23 | Transcript confidence and "correct this" on key facts | M | 3 | M | 3 | v0.92 | Report |
| 24 | Weekly coaching digest and "mark coached" | M | 3 | M | 3 | v0.92 | Report, Admin |
| 25 | Bilingual labels, either script, transliteration search | H | 2 | M | 3 | v0.92 | builder, tutorials |
| 26 | Voice result note after a call | H | 2 | M | 3 | v0.92 (gated) | Lead OS, Report |
| 27 | A 60-second "your week" recap | M | 2 | M | 2 | v0.92 | builder |

---

## The ideas

Each idea gives: **Problem** · **Evidence** · **Idea** · **Test** (the measure, the bar and
how it is read). Telemetry names refer to chapter 4 and `docs/product/telemetry-friction-lab.md`.
With tens of testers, tests compare the same people before and after a release, plus the
monthly think-aloud round; A/B tests wait for about 1,000 active sellers (chapter 3 §8.7).

### 1. Fix the Phone setup tile · H · S
- **Problem:** in the You sheet, "Phone setup" closes the sheet and opens nothing (3 of 3
  tries from Leads); from Settings → Selling it opens but the page jumps to Leads.
- **Evidence:** phone sweep finding 2 (P1). Without setup, calls aren't logged or recorded
  (chapter 1 recommendation 1: zero-tap capture is the core promise).
- **Idea:** open the flow in place from any screen (a sheet, not a navigation to /leads).
- **Test:** `phone_setup` flows started per week rise; none of the next round's testers hit
  a dead tile; no `dead_tap` finding on the You sheet.

### 2. "How did it go?" only after a real call, open within 1 s · H · S
- **Problem:** the question shows on leads with no new call, and after a call it isn't the
  first thing on screen.
- **Evidence:** phone sweep finding 3; people recall about 10% of a conversation five minutes
  later, and the end of the call is the strongest habit cue (chapter 2 §1, §6.3).
- **Idea:** show it only when the phone saw a call to this lead in the last 30 minutes, and
  bring it up within 1 s of returning from the dialler.
- **Test:** `log_result` runs started via `after_call` ≥ 80% of runs; finished share ≥ 85%;
  median time to finish ≤ 8 s (chapter 3 target for journey c).

### 3. Pressed state on every tap; gate on "no change" · H · S
- **Problem:** on production the first visible change comes about 0.25 s after a tap (the
  sheet sliding in), with no pressed state; a tab switch takes about 1–1.5 s.
- **Evidence:** phone sweep timings; the builder's pressed state passed on a real phone (grey
  within 0.2 s); feedback within 100 ms keeps a tap feeling direct (chapter 2 §6.4).
- **Idea:** one shared pressed style for every tappable, and the release gate also reads
  `sx.action_timing` results of "no change" on key actions.
- **Test:** key taps with no change in the first second < 2%; no `unresponsive` finding in
  the weekly report; p75 tap-to-settled on low-end phones within the chapter 3 budgets.

### 4. Speed-to-lead timer and urgent new-lead alert · H · S
- **Problem:** nobody sees how long a new lead has waited.
- **Evidence:** leads contacted within an hour were about seven times likelier to qualify
  (Oldroyd et al. 2011, via secondary summaries; chapter 1); Indian rivals alert at once.
  The new-lead card and urgent channel now exist (Lead OS, Android).
- **Idea:** a "waiting 12 min" chip on new leads, an urgent alert with a Call button for
  leads assigned to you, and minutes to first call per seller and source on the owner's view.
- **Test:** median minutes from arrival to first call falls by half within two weeks; share
  called within 5 minutes reported weekly.

### 5. Pre-chosen answers from the call's length · H · S
- **Problem:** every result starts from blank choices.
- **Evidence:** smart defaults are chapter 2's first recommendation; the phone already knows
  whether a call connected and for how long.
- **Idea:** under 10 s or not connected → "No answer" chosen; over 60 s → "We talked" chosen;
  the seller can change it.
- **Test:** `flow_blocked` at the reason and stage steps falls; `log_result` median time
  falls; changed defaults < 15% (if higher, the rule is wrong).

### 6. The screen matrix as a release gate (text size safe) · M · S
- **Problem:** in v0.89's matrix, every one of the 84 states of each screen had targets under
  44 px, up to 44 had cut text and up to 36 had text under 12.5 px; the lead sheet's "Call"
  and "WhatsApp" spilled at 115–130% text size.
- **Evidence:** the v0.89 matrix; budget phones and larger system fonts are common (chapter 2
  §6.4, §7.4).
- **Idea:** run `sx-matrix` in wb-ci for screens a change touches and fail on new "tiny",
  "clipped", "spill" or "small target" states.
- **Test:** the counts trend to zero by v0.92 and never rise in a release.

### 7. Tester missions for Play Alpha · H · S
- **Problem:** the Play production gate needs 12 testers opted in to Alpha for 14 days, and
  1 is; testers don't know what to try.
- **Evidence:** the Play tester note (25 Oct); a guided set of tasks is also the usability kit
  (chapter 7).
- **Idea:** a "Tester missions" card for Alpha users: take a lead, call, log a result, add a
  task, find a note, each ticked from the flow events; a thank-you and a one-tap feedback at
  the end.
- **Test:** testers opted in ≥ 12 and still active on day 14; missions finished per tester;
  the friction report's flows fill with real runs.

### 8. Xiaomi recordings-folder grant in the Play build · H · M
- **Problem:** on Xiaomi phones the Play build can't read the recorder folder; "Allow
  recordings" shows only red text, and setup stays at 3 of 9.
- **Evidence:** phone sweep finding 1 (P1); the folder-grant path is already the planned fix.
- **Idea:** the folder picker opened at the recorder's folder, with a one-screen picture of
  what to tap; the result in a corner card, not red text.
- **Test:** `permission_prompt` for `folder` granted ≥ 80% on Xiaomi; share of work calls
  with a recording on Xiaomi Play phones.

### 9. Four one-tap outcome tiles · H · M
- **Problem:** a result takes several choices (talked? what next? when?), and Save is often
  refused for something missing.
- **Evidence:** five choices or fewer, big targets in the thumb zone (chapter 2 §6.2, Hick's
  law, Fitts' law); chapter 3's KLM gives 5.2 s for the expert path.
- **Idea:** four tiles per organisation, each a whole result: "Interested, call tomorrow",
  "No answer, retry in 1 h", "Not interested", "Wrong number"; "More…" opens today's sheet.
- **Test:** `log_result` steps per run fall to 1–2; median ≤ 6 s; finished share up; SEQ in
  the kit ≥ 6.0.

### 10. A daily notification budget and digests · H · M
- **Problem:** reminders, alerts and nudges will multiply with the team engine.
- **Evidence:** each extra reminder cut acceptance about 30%; batching three times a day
  helped (chapter 2 §4).
- **Idea:** a per-seller daily budget across all kinds, tiers mapped to Android channels,
  nothing during a call, low-tier items batched into two or three digests.
- **Test:** notifications per seller per day; dismiss rate < 50%; channels turned off < 10%
  of sellers.

### 11. Drift nudge v1 with a holdout and a kill switch · H · M
- **Problem:** the owner wants drifting sellers brought back; nudges can annoy or feel like
  surveillance.
- **Evidence:** monitoring raises stress without raising performance unless light and
  developmental (chapter 2 §4.6); chapter 2 §8.4 specifies the rules. The nudge engine is off
  by default (Lead OS).
- **Idea:** ship chapter 2's version: private, two steps, a calm sound, "On a break", at most
  one sounded an hour and three a day, managers see only daily totals; keep 20% of sellers as
  a holdout for two weeks.
- **Test:** time back to the next call after a nudge vs the holdout; disable rate < 10%; stop
  the rollout if dismissals pass 60%.

### 12. Target framing: pace ring, stretch tier, "carried to tomorrow" · H · M
- **Problem:** targets are arriving (engine in v0.90); a hard daily line makes people stop at
  it or game it.
- **Evidence:** chapter 2 §3 (stopping at daily targets, gaming near the line, co-set goals).
- **Idea:** a weekly target shown as today's pace; base and stretch; "carried to tomorrow"
  instead of red; counts conversations and follow-ups from call records.
- **Test:** the share of seller-days ending exactly on the target stays low (a spike means
  stopping at the line); conversations per seller per week up.

### 13. In-app ease question and "why did you stop?" · H · M
- **Problem:** telemetry shows where people stop, not why.
- **Evidence:** chapter 3 §8.1 (micro-surveys, caps), the friction lab's "no end" and
  "left half way" counts.
- **Idea:** after a finished flow, one 7-point ease question (at most once a week per person);
  after a flow left half way, one tap from four reasons ("not now", "confusing", "didn't
  work", "something else").
- **Test:** response rate ≥ 20%; each top friction finding gets a reason within a week.

### 14. "One thing to try" shown before the next call · H · M
- **Problem:** coaching is read once (if at all) and forgotten by the next call.
- **Evidence:** if–then plans and one focus at a time (chapter 2 §2.3, §4.2, §8.4); coaching
  that overloads weaker sellers backfires (chapter 1).
- **Idea:** the report's one focus becomes a small card on the lead sheet and the call screen
  for the week ("Ask what they're comparing with before discounting").
- **Test:** the card is seen before ≥ 50% of calls; report coaching sections read rise; the
  skill's later trend once AC-SVAL clears scoring.

### 15. Permission explainer and blocked-permission rescue · M · S
- **Problem:** after two refusals Android stops asking; sellers don't know the way back.
- **Evidence:** per-brand setup guides are what users praise (chapter 1); the new
  `permission_prompt` outcome "blocked".
- **Idea:** before Android's dialog, one line and a picture of what it will look like; when
  blocked, a three-tap route to the app's settings with a picture per brand.
- **Test:** granted share per permission up; blocked share down; answer time down.

### 16. Monday fresh-start card · M · S
- **Problem:** weeks blur; a bad week drags into the next.
- **Evidence:** the fresh-start effect and personal bests (chapter 2 §3, §8.4).
- **Idea:** on Monday morning one card: last week's personal best and this week's pace.
- **Test:** time from Monday's first open to first call; Monday conversations vs other days.

### 17. Workspace identity band and empty-workspace guard · M · S
- **Problem:** a tester got confused switching organisation and account.
- **Evidence:** the owner's 25 Oct note; the friction lab's bounce and early-switch measures.
- **Idea:** the workspace's name and colour as a thin band on every screen; switching into a
  workspace with no leads says where the leads are ("Your leads are in …") before landing.
- **Test:** bounce people and switches within a minute of opening fall week on week.

### 18. UI language in telemetry · M · S
- **Problem:** we can't tell whether Hindi and Marathi users struggle more.
- **Evidence:** chapter 2 §7 (language, loanwords); no measured data yet.
- **Idea:** add the app's interface language (en, hi, mr) to each event's context, as a
  fixed value.
- **Test:** the friction report splits quick backs, dead taps and flow completion by language.

### 19. Bug reports carry the flow and step · M · S
- **Problem:** a report says "it didn't work" without where.
- **Evidence:** the bug reporter (23 Oct) and the friction lab's flows.
- **Idea:** attach the current flow and step, and the last five event names (codes only).
- **Test:** reports triaged without asking the tester a question rise.

### 20. Phone health per seller on the manager view · H · M
- **Problem:** a seller's phone silently stops logging (battery saver, autostart, folder).
- **Evidence:** chapter 1 recommendation 2; the phone's permission snapshot and device state.
- **Idea:** a green, amber or red dot per seller with the one fix, from the newest snapshot.
- **Test:** share of sellers green; work calls logged per seller per day.

### 21. "Next best lead" with its reason · H · M
- **Problem:** Today showed one test lead while 300+ waited (owner, 25 Oct).
- **Evidence:** naming one specific next action raises follow-through (implementation
  intentions, chapter 2 §4.2); My day is in the engine.
- **Idea:** Home's first card is the next lead and why ("asked for a call after lunch"), with
  Call.
- **Test:** time from opening the app to the first call; `lead_open_to_action` waits shorter.

### 22. Brief-first call report on the phone · H · M
- **Problem:** the report is long on a phone.
- **Evidence:** chapter 1 recommendation 3 (Gong and Salesloft brief patterns).
- **Idea:** a one-line recap, the agreed next step with one-tap task and WhatsApp, one focus
  skill; the full report a tap away.
- **Test:** quick backs on the report fall; reports leading to a task or message within 10
  minutes rise.

### 23. Transcript confidence and "correct this" on key facts · M · M
- **Problem:** code-mixed phone audio still has high error rates.
- **Evidence:** 16–30% error rates on Hinglish telephony (chapter 1); reviews punish silent
  errors.
- **Idea:** show low confidence on outcome, date and objection, with a one-tap correction.
- **Test:** corrections per 100 reports; "not helpful" taps fall.

### 24. Weekly coaching digest and "mark coached" · M · M
- **Problem:** managers don't know which calls to hear.
- **Evidence:** AI plus manager beat either alone (chapter 1); one weekly digest beats pushes
  per call (chapter 2).
- **Idea:** a Monday digest of three calls worth hearing per seller; "mark coached".
- **Test:** calls coached per manager per week; the digest opened ≥ 60%.

### 25. Bilingual labels, either script, transliteration search · H · M
- **Problem:** many sellers read Hindi or Marathi best and type in Roman script.
- **Evidence:** chapter 2 §7.
- **Idea:** key actions show a small Hindi or Marathi subtitle (loanwords kept: "Call",
  "Follow-up"); search finds "sharma" and "शर्मा" alike.
- **Test:** with idea 18, friction by language narrows; SEQ by language in the kit.

### 26. Voice result note after a call · H · M (gated)
- **Problem:** typed notes after calls are rare and slow.
- **Evidence:** voice beats typing for capture (chapter 2 §6.3, §7.4).
- **Idea:** hold to speak a note in any language; it becomes the note (and later a suggested
  result the seller confirms). Processing audio outside the phone needs the AC-GOV-AUD-001
  gates first, so v0.92 starts with on-phone dictation.
- **Test:** calls with a note rise; `log_result` time does not.

### 27. A 60-second "your week" recap · M · M
- **Problem:** effort is invisible to the seller.
- **Evidence:** informational, competence-building rewards (chapter 2 §2).
- **Idea:** a short weekly recap: conversations, follow-ups kept, one best moment; private.
- **Test:** opened ≥ 50%; week-2 retention of new sellers.

---

## What would change this ranking

- **The first real friction report** (staging now, production after a week of v0.89 data):
  any flow step where three or more people stop goes straight to the top.
- **The first think-aloud round** (chapter 7's kit): an idea testers don't need drops; a
  problem they all hit rises.
- **Effort estimates** are ours; the owning sessions should correct them before v0.90 is
  planned.
