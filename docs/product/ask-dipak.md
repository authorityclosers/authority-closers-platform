# Ask Dipak and the coaching loop

Ask Dipak is Dipak's sales-learning library: 10 categories, 150 questions with stable IDs, and 12 complete lessons. Its sources are Dipak's spec and clickable sample, dated 13 Nov 2026. It is not a chatbot.

The coaching loop around it comes from the 13 Nov 2026 meeting (section 5; decisions D7, D9 and D10):

1. A report's weaknesses lead to Dipak's questions.
2. Reading a lesson, the seller ticks its Next-call mission.
3. The seller keeps up to three ticked missions active.
4. After each call, the seller answers yes or no for each active mission.
5. The count per mission is the number of calls it was done on. The seller sees their own counts; the owner sees every seller's.

Nothing else is tracked or scored. A tick or a "yes" is the seller's own word, never proof of what happened on a call.

## Where things live

| What                              | Where                                                                                                                                                                             |
| --------------------------------- | --------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- |
| The library, word for word        | `apps/sales-xray-web/app/ask-dipak/library.json` (the app). The server has the same file at `packages/python/ac_platform/ask_dipak/library.json`, and a test keeps the two equal. |
| Dipak's internal coaching notes   | `apps/sales-xray-web/app/ask-dipak/coach-notes.json`. No screen, API, MCP tool or CLI command serves them.                                                                        |
| Saved lessons and ticked missions | Table `sales_xray_ask_dipak_events` (migration 0153): saved, unsaved, mission_done, mission_undone.                                                                               |
| Active missions                   | Table `sales_xray_ask_dipak_focus_events` (migration 0155): activated, deactivated.                                                                                               |
| After-call answers                | Table `sales_xray_ask_dipak_call_checks` (migration 0155): one row per answer, linked to the call and the lead.                                                                   |
| Report → questions table          | `packages/python/ac_platform/ask_dipak/how_to_improve.py`                                                                                                                         |

### How the tables work

All three tables are append-only. Where a person stands is folded from their newest rows.

- Unticking a mission also drops it from the active three.
- A call is the lead's call event, because the after-call question comes before any recording exists. When the call is also analysed, it is the analysed call too. Answering by either ID gives one answer per mission.
- All three tables are erased with the person's account.

## The app's API (signed-in person, Sales X-Ray hosts)

Writes need the app's own origin. Every answer is `private, no-store`.

| Method and path                                                                      | What it does                                                                                                                    |
| ------------------------------------------------------------------------------------ | ------------------------------------------------------------------------------------------------------------------------------- |
| `GET /v1/sales-xray/ask-dipak/progress`                                              | `{saved, missions, missions_done}`                                                                                              |
| `PUT /v1/sales-xray/ask-dipak/progress/{id}` `{item: saved\|mission, on}`            | Saves or clears a bookmark, or ticks or unticks a mission.                                                                      |
| `GET /v1/sales-xray/ask-dipak/lessons?q=`                                            | Keyword search, the app's own: titles, categories, IDs and aliases. An empty `q` gives the six suggestions.                     |
| `GET /v1/sales-xray/ask-dipak/lessons/{id}`                                          | `{question, lesson}`. `lesson` is null while the question has none.                                                             |
| `GET /v1/sales-xray/ask-dipak/how-to-improve?skills=&objections=`                    | Dipak's questions for a report's weaknesses (see the table below).                                                              |
| `GET /v1/sales-xray/ask-dipak/growth`                                                | `{max_active, active, missions[]}`. Each mission has `active`, `ticked`, `done_calls`, `not_done_calls` and `last_answered_at`. |
| `PUT /v1/sales-xray/ask-dipak/focus/{id}` `{active}`                                 | Makes a ticked mission active or drops it. A fourth active mission is refused with 409.                                         |
| `GET /v1/sales-xray/ask-dipak/calls`                                                 | My latest calls from leads in this workspace. Each lists `waiting`: the active missions not yet answered for it.                |
| `GET /v1/sales-xray/ask-dipak/calls/{call}/check`                                    | The after-call question for one of my calls.                                                                                    |
| `PUT /v1/sales-xray/ask-dipak/calls/{call}/check` `{answers: [{question_id, done}]}` | Records my yes or no. Only an active mission, or one already answered for this call, can be answered.                           |
| `GET /v1/sales-xray/ask-dipak/team`                                                  | Every current seller's missions and counts in this workspace. Owner, admin, manager and viewer only.                            |

`{call}` is the lead's call event ID or the analysed call's ID. Another person's call answers 404.

## For Claude and other apps: API keys, connected apps, MCP and the CLI

Everything above is also served through the integrations `Reader` (`ask_dipak/integration.py`). The same key scopes, plan tiers, rate limits and role rules apply as for calls.

### Scopes

The orchestrator set these on 14 Nov 2026, mirroring the call scopes. No plan or price changed.

| Scope            | Who can hold it                                            | What it allows                                                                                                   | Plans                                       |
| ---------------- | ---------------------------------------------------------- | ---------------------------------------------------------------------------------------------------------------- | ------------------------------------------- |
| (none)           | any key or connection                                      | Lessons, search, "how to improve"                                                                                | all                                         |
| `coaching:read`  | API keys and connected apps                                | My missions and counts, my latest calls. The team's counts for an organisation key or a role that sees the team. | the same as `calls:read` (trial and up)     |
| `coaching:write` | connected apps only (`APP_SCOPES`), acting as their person | Save lessons, tick missions, keep up to three active, answer after a call                                        | the same as `calls:write` (Personal and up) |

Missions belong to a person. An organisation's API key gets `person_only` for them and can read only the team's counts.

> **Note:** the scope lists for each tier are code defaults (`tier_policy.DEFAULTS`). A workspace whose platform settings were saved before the coaching scopes existed keeps its saved lists until they are saved again.

### API routes, under `/v1/api/ask-dipak`

| Method and path                                               | Scope                                           |
| ------------------------------------------------------------- | ----------------------------------------------- |
| `GET lessons?q=` and `GET lessons/{id}`                       | none                                            |
| `GET how-to-improve?skills=a,b&objections=c`                  | none                                            |
| `GET missions`, `GET calls`, `GET calls/{call}/check`         | `coaching:read`                                 |
| `GET team`                                                    | `coaching:read` (organisation key or team role) |
| `PUT saved/{id}`, `PUT ticked/{id}`, `PUT active/{id}` `{on}` | `coaching:write`                                |
| `PUT calls/{call}/check` `{answers: [{question_id, done}]}`   | `coaching:write`                                |

### MCP tools, on the remote server `/v1/mcp`

| Tools                                                                                              | Scope            |
| -------------------------------------------------------------------------------------------------- | ---------------- |
| `ask_dipak_search`, `ask_dipak_lesson`, `ask_dipak_how_to_improve`                                 | none             |
| `ask_dipak_my_missions`, `ask_dipak_recent_calls`, `ask_dipak_team_missions`                       | `coaching:read`  |
| `ask_dipak_save_lesson`, `ask_dipak_tick_mission`, `ask_dipak_set_active`, `ask_dipak_answer_call` | `coaching:write` |

Every write is idempotent: the same change twice changes nothing. The MCP resource metadata offers both coaching scopes (`oauth_http.MCP_SCOPES`). A connector that asks for no scope still gets only `calls:read reports:read leads:read`, so it sees just the lesson tools.

### CLI: `sx dipak` (`/developers/sx.py`)

```
sx dipak search [WORDS]          sx dipak lesson PB03
sx dipak improve --skills closing_decision_management --objections stall
sx dipak missions | calls | team
sx dipak save|tick|active QUESTION_ID [--off]
sx dipak answer CALL_ID QUESTION_ID yes|no
```

`SX_API_KEY` can be:

- an organisation key (`sxk_`), for lessons and the team's counts;
- a connected app's token (`sxa_`), to act as that person.

## Report → "How to improve"

A report's weaknesses are:

- its skills whose `call_state` is `needs_attention`, in the report's order;
- the kinds of objection raised on the call (`call_map.objections[].kind`).

`how_to_improve.questions_for` takes one question per weakness first, then each weakness's next one, never the same question twice, and returns up to 4. `how_to_improve.for_report(report)` does the same for a report's JSON.

The table below is the one in the code, printed for Dipak to review. To change a row, edit `how_to_improve.py`; its test checks that every ID is one of Dipak's 150.

| Report skill (`dimension_id`)      | Dipak's questions, in order                                                                                                                                                                                            |
| ---------------------------------- | ---------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- |
| `human_connection_trust`           | RP01 — What is rapport, really? (lesson ready)<br>RP02 — How do I build trust with someone I've just met?<br>RP04 — Should I agree with the customer to build rapport?                                                 |
| `discovery_deep_understanding`     | PG01 — How do I find the customer's real problem? (lesson ready)<br>LI01 — What does good listening actually mean in sales?<br>AQ03 — How do I ask deeper questions naturally?                                         |
| `qualification`                    | DM01 — How do I identify who makes the buying decision? (lesson ready)<br>DM02 — “मुझे wife/partner से पूछना है।” क्या यह objection है? (lesson ready)<br>DP02 — What's the difference between interest and readiness? |
| `problem_impact_desire`            | IM01 — Why is understanding the problem alone not enough? (lesson ready)<br>IM02 — How do I help customers see what a problem is costing them?<br>PG03 — How do I understand what the customer truly wants?            |
| `solution_relevance_presentation`  | EX02 — Features, benefits and outcomes: what is the difference? (lesson ready)<br>MS04 — How do I connect my solution to the actual problem?<br>MS02 — Why is pitching too early a bad idea?                           |
| `certainty_objection_intelligence` | PB03 — Customer कहता है, “Price बहुत high है।” क्या करूँ? (lesson ready)<br>OB03 — Customer बोलता है, “मैं सोचकर बताऊँगा।” अब क्या करूँ? (lesson ready)<br>OB02 — How do I find the real reason behind an objection?   |
| `closing_decision_management`      | NX02 — How do I secure a meaningful next step? (lesson ready)<br>CL01 — When is the right time to close?<br>CL04 — What if they are interested but do not decide?                                                      |
| `communication_tonality`           | TP03 — When should I pause during a sales call? (lesson ready)<br>TP02 — How do I know whether I'm speaking too fast?<br>TP05 — How can I sound confident without sounding aggressive?                                 |

| Objection (`call_map.objections[].kind`) | Dipak's questions, in order                                                                                                                                                                                 |
| ---------------------------------------- | ----------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- |
| `price_concern`                          | PB03 — Customer कहता है, “Price बहुत high है।” क्या करूँ? (lesson ready)<br>PB04 — Is it really a budget problem?<br>PB05 — When should I offer a discount?                                                 |
| `affordability_gap`                      | PB04 — Is it really a budget problem?<br>PB03 — Customer कहता है, “Price बहुत high है।” क्या करूँ? (lesson ready)<br>NEW-033 — How do I negotiate approved payment terms?                                   |
| `time_constraint`                        | NEW-031 — What if they say 'I don't have time'?<br>OB03 — Customer बोलता है, “मैं सोचकर बताऊँगा।” अब क्या करूँ? (lesson ready)                                                                              |
| `stall`                                  | OB03 — Customer बोलता है, “मैं सोचकर बताऊँगा।” अब क्या करूँ? (lesson ready)<br>CL04 — What if they are interested but do not decide?<br>NEW-029 — When should I stop handling an objection and accept 'no'? |
| `competitor_or_status_quo`               | OB02 — How do I find the real reason behind an objection?<br>OB04 — What if they tried a similar solution and failed?<br>NEW-032 — How do I understand what failed last time?                               |
| `decision_maker_absent`                  | DM02 — “मुझे wife/partner से पूछना है।” क्या यह objection है? (lesson ready)<br>DM05 — What if the person can't make the final decision?<br>DM03 — When should I involve another decision-maker?            |
| `trust_concern`                          | NEW-005 — How do I build trust after a bad experience?<br>RP02 — How do I build trust with someone I've just met?<br>NEW-007 — How do I rebuild trust after misunderstanding?                               |
| `other`                                  | OB02 — How do I find the real reason behind an objection?<br>OB01 — What is an objection and why does it happen?                                                                                            |

Fallback when nothing above applies: NEW-035 — How do I use Sales X-Ray coaching for my next five calls?, CO02 — How do I identify my biggest weakness?.
