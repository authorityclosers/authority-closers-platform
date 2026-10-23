# Lead OS: design for L1–L7 (L0, 24 Oct 2026)

This design is grounded in the dev workbench at tip `14894299`. Paths are relative to `packages/python/ac_platform/lead_desk/` (Python) or `apps/sales-xray-web/app/` (web), unless written in full. At L1 this file is copied to `docs/product/lead-desk/lead-os-design.md`.

## 0. Key decisions

1. **Junk is a 7th desk kind, `junk`, not a flag.** One current-stage column stays the single truth.
2. **Transition rules live inside the journey version JSON.** Each stage gets `moves`, `needs`, `reasons` and `rot_hours`, so rules need **no migration**. A stage without `moves` is permissive, so every existing org behaves exactly as today.
3. **One writer for every stage change** (`journey/transitions.py`). It writes **exactly one `stage` event** per (stage, step) change, using the v2 shape with `source`. Calls, board, table, bulk, import, meetings, rules and merges all go through it.
4. **Meetings get their own table** for current state; their history goes in `meeting` events. At most one scheduled meeting per lead, enforced by the database.
5. **Duplicates: an identity table plus a reversible merge.** The loser is kept with `merged_into_id`, and its events are never moved. Exact matches attach on arrival; fuzzy matches go to review.
6. **Three migrations in total:** L1 core, L5 benchmark runs, L6 duplicates. Rules, reason lists and graphs are data.

## 1. Current state map (what exists, what we reuse)

| Area | Where | Today | Lead OS |
|---|---|---|---|
| Lead row | `models.py:37-130` | `stage` is one of 6 kinds (check `lead_desk_lead_stage`, l.54). Also `step`, `pipeline_key`, `next_action_at/note`, `attempts`, `last_result`, `first/last_contact_at`, `repeats`, `test_data`. The unique `(tenant, phone)` index (l.66) already stops exact phone duplicates. | Extend: `junk`, `stage_at`, `outcome_reason` (L1); `merged_into_id/at` (L6) |
| History | `models.py:133-170` `LeadEvent` | Append-only. Kinds: captured, repeat, assigned, reassigned, call, result, note, edited, message, scheduled, stage (check l.140). Has an idempotent `command_id` (l.152). | Add kinds `meeting`, `suggestion` (L1) and `merged` (L6) |
| Event writer | `store.py:447 _event` | Writes events a microsecond apart within one request | Reuse |
| Stage moves | `store.py:1305 to_stage` (from the move route `journey/http.py:735`, bulk `store.py:1408` and import `intake.py:270`); `store.py:1657 dispose` (call result) | Two writers. `dispose` writes a `result` event with from/to; `to_stage` writes a `stage` event. Neither checks transitions or asks for reasons. The move route refuses Not connected (`journey/http.py:~760`). | Both call the new single writer |
| Call result logic | `vocabulary.py:149-182` | NeoDove retry rule (1 h, then 1 d). `stage_after_not_connected` keeps follow_up and interested leads where they are. Ten reasons for not connecting, three of them bad-number. `CLOSED_STAGES={won,lost}`. | Reuse. Add `junk` to the stage sets. Retry spacing becomes a rule |
| Repeat / reopen | `store.py:1462 _repeat` | The same phone again gives a `repeat` event. A won or lost lead is auto-reopened to `new` and re-allocated. | Keep for Lost. Junk stays Junk. Won is an owner question (§10) |
| Capture dedupe | `store.py:1132 ingest`, `capture.py:142 normalise_phone` | Matches on source_ref, then exact E.164 phone, and catches the race through IntegrityError. Email is **not** used. | L6: identity table (phone, email, Meta lead id, wa_id) |
| Journey | `journey/model.py` (`Stage` l.60, `resolve` l.100, `check` l.298, `build` l.237, `from_template` l.321, `save` l.347, `lead_counts` l.199) and `journey/templates.py` (12 templates, `Kind` l.25, `MILESTONE_KIND` l.100, `guess_milestone` l.385) | Append-only versions per pipeline. A stage is {key, label, kind, milestone, archived, origin, ref}. `from_rows` skips unknown keys, so it is forward-compatible. | Add stage fields, a new template, `disqualified` milestone |
| Suggestions | `journey/signals.py:190 lead_suggestion`, shown in `journey/stage-suggestion.tsx` and the after-call picker (`leads/lead-sheet.tsx:192 stageChoices`, `:274 CallOutcome`) | Reads `call_objects` (`outcome.call_outcome`, `commitment.follow_up/next_step`) and suggests only "ahead" moves. Time, meeting and reason are not used. | Extend into a full proposal (§6) |
| Call facts | `call_data/taxonomy.py:416-495` | `commitment.follow_up` is {text, date, time, purpose}. Call outcomes: deal_closed, follow_up_agreed, meeting_scheduled, no_sale, not_a_fit, callback_requested, no_conversation. Objection kinds: price, timing, authority, need, trust, competition. Also `signal.interest` and `signal.urgency`. | Read-only input |
| Reminders | `push.py:226-248` | A due alert goes out once per `next_action_at` (`alerted_due_at`). FCM carries ids only. | Add a meeting reminder, once per `starts_at` |
| SLA | `sla.py` (settings key `sla`) | First-response target, breaches table and alerts | Reuse; the builder edits it |
| Reports | `store.py:2634 performance` (calls, connected, interested, won and new per period; open counts per kind); `journey/model.py:199 lead_counts` (each lead once per stage) | No funnel from history, no reasons, no junk, no "no next action" | New `reports.py` (§7) |
| Ad engine | `journey/engine.py:72 reached`; `connectors/meta_capi.py:65 STAGES` | Reads `result`/`stage` events. Meta's `stages_reached` filters to the 6 kinds, so junk is never written to `lead_desk_meta_conversions` and its check needs no change. | Junk maps to `disqualified`, unmapped by default |
| Partner webhooks | `partner_events/lead_events.py:47,56,231` | Builds `lead.stage_changed`/`closed` **from `result` events only**, so board moves send nothing today | Read `stage` events and add junk (coordinate, §10) |
| Web list/table | `leads/list-view.tsx`, `leads-table.tsx` (computer only, ≥1100 px), `table-edit.tsx` (inline name/phone/stage/owner/pipeline), `stage-tabs.tsx` (`KIND_ORDER`), `lead-filters.tsx` (who/pipeline/q), `saved-views.ts` (on the device; also a link), `bulk-sheet.tsx`, `gestures.ts` (swipe/hold) | Paged by 50 with offset, filtered by kind only. No board, no windowing. | Reuse the shell, rows, keys and edit flow |
| Web lead sheet | `leads/lead-sheet.tsx` (`History` l.871+, `CallOutcome`, `LeadCard` l.1849) | History list, after-call picker, follow-up time picker (`TIMES`) | The timeline replaces `History`; the sheets reuse `TimePicker` |
| Journey page | `leads/journey/journey-view.tsx` (1203 lines) | Single cluttered page: template pick, stage editor, ad platforms | L4 builder replaces the editor part |
| Tests | `tests/database/test_lead_desk_*_postgresql.py`, `tests/unit/lead_desk/test_journey*.py`, `tests/infra/test_lead_desk_*_backup_parity.py`, `leads/*.test.tsx`, `tests/e2e/workbench/` | — | Follow the same patterns |

## 2. Data model deltas

### 2.1 Junk: a 7th kind, recommended over a flag

- **Why a kind.** A flag allows "Lost and junk" or "Interested and junk", which breaks "one current stage" (AT12). Every query would also need a second predicate. As a kind, junk is closed, has no next action, and is excluded from the funnel naturally (`Journey.funnel()`).
- **Migration (L1):** drop and recreate `ck_lead_desk_leads_lead_desk_lead_stage` with `'junk'`, following the pattern 0111 used for the event-kind check.
  - `lead_desk_meta_conversions.stage` stays untouched; the legacy sender never emits junk.
  - Rollback is allowed only while no lead has stage `junk`.
- **Code changes:**
  - `vocabulary.py`: add junk to `STAGES`, `CLOSED_STAGES` and `STAGE_LABELS["junk"]="Junk"`.
  - `templates.py`: add junk to `Kind`/`KINDS`/`KIND_WORDS`. Add the new milestone `disqualified` ("Fake or unusable") with `MILESTONE_KIND[disqualified]=junk`, kept out of `FUNNEL_ORDER`.
  - `guess_milestone`: "junk|spam|fake|invalid|wrong number" now gives `disqualified` instead of `lost`.
  - `model.check`: at most 1 live junk stage.
  - `mapping.py`: `disqualified` is unmapped by default.
  - `partner_events` (coordinated).
  - Web: the `Stage` union (`leads-client.ts:61`), `Kind` (`journey-client.ts:9`), `KIND_ORDER`/`KIND_WORDS`, `TONES` and the table-edit choices.
- **Older six-kind templates:** they have no junk stage, so `resolve('junk', None)` returns None and the label falls back to "Junk". Every org can mark Junk from day one, and the board always shows a Junk group.

### 2.2 New lead columns (L1)

| Column | Type | Purpose | Existing rows |
|---|---|---|---|
| `stage_at` | timestamptz NULL | When the lead entered its current (stage, step). Drives ageing, the rot dot and the board sort. | Backfilled in the migration: the latest `captured`, reopened `repeat`, stage-changing `result`, or `stage` event; else `created_at` |
| `outcome_reason` | varchar(40) NULL, check `outcome_reason IS NULL OR stage IN ('lost','junk')` | Current Lost/Junk reason key for filters and reports. Cleared on reopen; history keeps every reason. | NULL ("Not recorded") |

There is one new index, `ix_lead_desk_lead_stage_at (tenant_id, stage, stage_at)`.

### 2.3 The stage-change event (v2) and the single writer

`journey/transitions.py` has two parts:
- `check(journey, lead, target, payload, viewer) -> Allowed | Needs | Refused` is pure.
- `LeadDesk._move(lead, target, payload, source, via, command_id)` is the only code that changes `stage`/`step`. It:
  - sets `stage_at`, `outcome_reason`, `next_action_*` and `revision`;
  - writes **one** `stage` event;
  - closes or opens meetings as needed.

`LeadEvent(kind='stage').data`, with the actor in `actor_person_id` and the time in `created_at`:

```json
{ "v": 2, "action": "move|close|reopen|reclassify",
  "from_kind": "new", "from_step": "new", "from_label": "New Lead",
  "to_kind": "interested", "to_step": "meeting_scheduled", "to_label": "Meeting / Demo Scheduled",
  "reason": "price|null", "reason_label": "Price or budget", "note": "…|null",
  "source": "seller|ai_suggestion|rule|import|merge|capture|template",
  "via": "board|sheet|after_call|table|bulk|meeting|chat|api|null",
  "contact": "call|reply|seller_said|null",
  "meeting_id": "uuid|null", "next_action_at": "iso|null",
  "suggestion": {"ref": "call:<fact id>", "from": "call|chat|rule", "changed": false},
  "rule_id": "idle_close|null", "result_event_id": "uuid|null", "pipeline": "main",
  "stage": "interested", "from_stage": "new", "step": "meeting_scheduled",
  "step_label": "Meeting / Demo Scheduled", "remark": "…" }
```

- **Legacy keys.** The last five keys are the legacy ones. They are kept so that `engine.reached`, `performance()`, `signals.heard` and the import paths read v2 events unchanged.
- **`dispose` (call result).** It keeps writing its `result` event, for calls and attempts. When the stage changes, it also writes the `stage` event, and `result.data.stage_event_id` points at it.
  - The timeline folds the two into one call row.
  - The engine skips `result` events that carry `stage_event_id`.
  - Reports read `stage` events, plus legacy `result` events (with `stage≠from_stage` and no `stage_event_id`) through a compatibility reader.
  - No history is rewritten.

### 2.4 Transition rules per template version: no migration

Each stage dict in `lead_desk_journey_versions.stages` gains optional keys, and `Stage` gains matching fields. `as_json` writes them only when set, so old rows stay byte-identical.

| Key | Meaning | Absent |
|---|---|---|
| `moves: [step…]` | Allowed targets from this stage. For a closed stage, these are the reopen targets. | Any live stage (permissive, as today) |
| `needs: [...]` | Asked on **entry**. Values are `next_action`, `meeting`, `meeting_done`, `reason`, `nc_reason` and `confirm`. | Implicit defaults: Lost gets reason prompted but skippable, plus confirm; Junk gets reason **required** plus confirm; Won gets confirm |
| `reasons: [{key,label}]` | Reason list, on lost and junk stages only. The key `other` always needs a note. | Default lists (§3) |
| `rot_hours: int` | Idle hours before the card shows ageing | No dot |

Server rules:
- The server refuses a move outside `moves` with 409 and plain words, plus `allowed`.
- It refuses a move with missing needs with 422 plus `needs: [...]`, so the client opens the sheet and asks only for those.
- Imports (`source=import`) skip `moves` but not `reason`; the default reason is "Imported as lost".
- `Won→Junk` and `Lost→Junk` (reclassify) are allowed only for the owner or admin.

### 2.5 Meetings: a table plus events (recommended over events only)

The current state needs:
- one scheduled meeting per lead;
- an agenda by time;
- a reminder once per start time;
- rescheduling in place.

Folding events on every read would be slow and fragile, so current state goes in a table and history in events.

`lead_desk_meetings` (L1) has these columns:
- `id` (pk);
- `tenant_id`, `lead_id`, with a foreign key to (tenant, lead);
- `revision` (≥1);
- `status` ∈ (`scheduled`, `done`, `missed`, `cancelled`);
- `starts_at`;
- `duration_minutes` (5–480, default 30);
- `mode` ∈ (`zoom`, `google_meet`, `phone`, `in_person`, `other`);
- `link` varchar(500) NULL (https only, checked in code);
- `location` varchar(300) NULL;
- `agenda` varchar(1000) NULL;
- `outcome_note` varchar(1000) NULL;
- `host_person_id` NULL, with a foreign key to memberships;
- `reminded_for` timestamptz NULL (the `starts_at` already reminded);
- `created_by_person_id`, `created_at`, `updated_at`, `closed_at`.

Checks and indexes:
- Check: `(status='scheduled') = (closed_at IS NULL)`.
- **Unique partial index on `(tenant_id, lead_id) WHERE status='scheduled'`.** A postponed meeting updates the existing row (with history kept in events); it never creates a second one.
- Index on `(tenant_id, starts_at) WHERE status='scheduled'`, for the agenda and reminders.

History is the `meeting` event: `{meeting_id, action: scheduled|rescheduled|done|missed|cancelled, starts_at, from_starts_at, mode, from_mode, location, has_link, note}`.

Rules:
- Scheduling sets `lead.next_action_at = starts_at`.
- **Done** marks the meeting done and moves the lead to the template's `appointment_done` stage.
- **Missed** and **Cancelled** close the meeting and ask for the target (NC, Interested or DI) plus the next action.

### 2.6 Reopen, reassign and repeat

- **Reopen** uses `POST …/reopen`. It works from won, lost or junk, and only to the closed stage's `moves`. The default target is the `from_step` of the closing event, and `next_action` is required.
  - It clears `outcome_reason`, writes a `stage` event with `action=reopen`, and keeps everything else.
  - Reopening a Won lead is for the owner or admin only.
- **Reassign:** the existing `reassigned` events stay as they are; only a test is added (AT15).
- **Repeat capture:**
  - **lost:** auto-reopen as today, now also writing a `stage` event with `source=capture` and `action=reopen`.
  - **junk:** stays junk. A `repeat` event is written with `reopened=false`, plus a "Came again, reopen?" suggestion for the owner.
  - **won:** the owner decides (§10).

### 2.7 Duplicates and merge (L6)

- **`lead_desk_identities`.** Columns: `(tenant_id, kind ∈ phone|email|meta_lead|wa_id, value, lead_id, source, created_at)`, primary key `(tenant_id, kind, value)`, index `(tenant_id, lead_id)`.
  - The migration backfills it from `leads.phone` and `lower(email)` with ON CONFLICT DO NOTHING. A conflicting email becomes a review pair.
  - The phone book and call-log matching also read secondary phones from it.
- **On `lead_desk_leads`:**
  - `merged_into_id uuid NULL`, with a foreign key to (tenant, id) and a check that it is not the lead itself;
  - `merged_at`, with the check `(merged_into_id IS NULL) = (merged_at IS NULL)`;
  - `_visible()` (`store.py:472`) adds `merged_into_id IS NULL`, which hides merged leads everywhere from one place.
- **`lead_desk_duplicate_pairs`.**
  - Columns: `(id, tenant_id, lead_a < lead_b, reasons JSON, score 0-100, status ∈ open|merged|dismissed, decided_by, decided_at, created_at)`.
  - Unique on `(tenant_id, lead_a, lead_b)`.
- The event check gains `merged`.
- **Arrival:**
  - Any exact identity hit is followed through `merged_into_id` to the surviving lead. It gets a `repeat` event ("came again via <source>"), and new identities are added to that lead.
  - If the phone hits lead A and the email hits lead B, the arrival attaches to A and the pair (A, B) is opened for review.
  - A second record is never created when an exact identity hits.
- **Fuzzy pairs** are found on arrival and in a daily sweep:
  - the same last 10 digits under a different country code or format;
  - the same normalised name (honorifics stripped) plus the same city or company, within 30 days;
  - name token Jaccard ≥0.8 plus the same source, within 1 day;
  - a lead's phone appearing in another lead's payload.
- **Merge:**
  - The survivor's empty fields are filled from the loser, and the before-values are recorded in the `merged` event.
  - The loser gets `merged_into_id`.
  - The survivor's timeline shows the loser's events, read with `lead_id IN (survivor, merged…)`.
  - **Unmerge** clears `merged_into_id` and restores the fields from the event.
  - Nothing is deleted.

### 2.8 Rules, suggestions and benchmark runs

- **Rules:** stored at `lead_desk_settings.config["lead_rules"]`, which bumps the row revision.
  - Every change writes an `AuditRepository.append` row (`action="lead_desk.rules.changed"`, before/after diff). The same pattern is used at `store.py:2032`.
  - No migration.
- **Suggestions** are computed on read and never stored as state.
  - An accepted suggestion goes in the `stage` event (`source=ai_suggestion`, `suggestion.ref`).
  - Offered rule hints (the junk hint) and dismissals write a `suggestion` event, which makes the logging auditable.
- **`lead_desk_benchmark_runs` (L5)** is append-only. Columns: `(id, tenant_id, pipeline_key, journey_version, rules_revision, seed, params JSON, metrics JSON, passed bool, created_by_person_id, created_at)`.

### 2.9 Migrations: exact list and compatibility

| # | Phase | Tables/columns | Backfill | Rollback |
|---|---|---|---|---|
| A | L1 | `lead_desk_leads`: stage check +junk, `+stage_at`, `+outcome_reason` (with check), `+ix_lead_desk_lead_stage_at`. `lead_desk_events`: kind check +`meeting`,`suggestion`. New `lead_desk_meetings`. | `stage_at` from events (one UPDATE…FROM) | While there are no junk leads, no meetings, and no meeting or suggestion events |
| B | L5 | New `lead_desk_benchmark_runs` | — | While empty |
| C | L6 | New `lead_desk_identities` and `lead_desk_duplicate_pairs`. `lead_desk_leads` `+merged_into_id`, `+merged_at`. Event check +`merged`. | Identities from phone/email | While nothing is merged |

- Align 3 assigns the numbers; the next free is after 0127.
- Each migration gets `tests/database/test_lead_desk_<name>_migration_postgresql.py` and `tests/infra/test_lead_desk_<name>_backup_parity.py`, and updates `tests/database/test_model_registry.py`.
- The new tables are added to `infra/vps-foundation/scripts/ac-postgres-backup.py`, `infra/application/scripts/restore-drill.py` and `infra/vps-foundation/scripts/ac-restic-postgres-restore-proof.py`. These files are outside our lane, so this needs coordination with Align.

**Compatibility:**
- Existing leads keep their (stage, step), and their events are not rewritten.
- Existing versions have no `moves`, so they stay permissive.
- The old web client keeps working: the new fields are additive, and the app and the web deploy together.
- The MCP `list_leads`/`get_lead` tools are read-only and only see additive fields.
- Webhooks get the new enum value `junk` (additive; to be announced in the developer docs).

## 3. The new generic template: "Inside sales with demos"

The id is `inside_sales_demos`, the icon `phone`, and the blurb "Call, book a demo, close. Junk kept apart." AC picks it as data, and the code names no customer.

| # | key | Label (exact) | kind | milestone | needs on entry | moves (allowed targets) | rot_hours |
|---|---|---|---|---|---|---|---|
| 1 | `new` | New Lead | new | lead | — | not_connected, interested, discussion_incomplete¹, meeting_scheduled, lost, junk | 1 |
| 2 | `not_connected` | Not Connected | not_connected | unreachable | nc_reason, next_action (prefilled from the retry rule) | interested, discussion_incomplete, meeting_scheduled¹, lost¹, junk | 48 |
| 3 | `interested` | Interested (In Follow-Up) | interested | qualified | next_action (call / WhatsApp / other + when) | discussion_incomplete, meeting_scheduled, lost, junk | 72 |
| 4 | `discussion_incomplete` | Discussion Incomplete | follow_up | contacted | next_action (resume time) | interested, meeting_scheduled, lost, junk | 24 |
| 5 | `meeting_scheduled` | Meeting / Demo Scheduled | interested | appointment_booked | meeting (date, time, mode, link or location) | demo_completed, not_connected, interested, discussion_incomplete, lost, junk | starts_at + 2 h with no outcome |
| 6 | `demo_completed` | Demo / Zoom Meeting Completed | interested | appointment_done | meeting_done, next_action (note prompted) | won, lost, junk. Staying is a follow-up, not a move. | 120 |
| 7 | `won` | Closed / Won | won | won | confirm | reopen: interested, discussion_incomplete, meeting_scheduled, demo_completed; reclassify: junk (managers) | — |
| 8 | `lost` | Closed / Lost | lost | lost | reason, confirm | reopen: not_connected, interested, discussion_incomplete, meeting_scheduled, demo_completed; reclassify: junk | — |
| 9 | `junk` | Junk Lead | junk | disqualified | reason, confirm | reopen: new, not_connected, interested, discussion_incomplete | — |

¹ The spec requires that a conversation happened for these moves. This is recorded, not blocking:
- When the move comes from a connected call, the event gets `contact=call`.
- From the board, the sheet says "This records that you spoke to them" and sets `contact=seller_said`.

Notes:
- **Old Follow-up leads.** In the six-kind default, `follow_up` leads have `step=None`. When an org adopts this template, they resolve to Discussion Incomplete (the first live follow_up stage). The apply step therefore asks for a mapping of each old stage that has leads (§5 builder). For AC on production, that mapping is an owner-approved data change.
- **Interested + unanswered call.** A not-connected call on an Interested, DI, Meeting or Demo-done lead keeps its stage (`stage_after_not_connected`). This is right: those leads stay Interested even when one call goes unanswered.
- **Lost reasons** (`reasons` on `lost`):
  - not_interested "Not interested"
  - chose_other "Chose another provider"
  - declined_offer "Declined the offer"
  - decided_not_to_proceed "Decided not to proceed"
  - no_response "No response after follow-ups"
  - price "Price or budget"²
  - not_now "Not the right time"²
  - not_a_fit "Not a fit"²
  - other "Other" (note required)
- **Junk reasons** (`reasons` on `junk`):
  - fake "Fake enquiry"
  - invalid_number "Wrong or invalid number"
  - someone_else "Number belongs to someone else"
  - unusable_contact "Contact details unusable"
  - unreachable_verified "Switched off or unreachable after checks"
  - spam_test "Spam or test entry"
  - other "Other" (note required)

² These three are added beyond the spec's list, so that call objections (price, timing, need) map onto a reason. The sales lead should confirm them (§10).

## 4. API changes (all under `/v1/lead-desk`, additive)

| Endpoint | Change |
|---|---|
| `POST /leads/{id}/stage` (MoveCommand, `journey/http.py:179,735`) | Adds `reason`, `reasonNote`, `ncReason`, `nextActionAt`, `nextActionKind`, `meeting{startsAt,durationMinutes,mode,link,location}`, `confirm`, `contact`, `source` (`seller` or `ai_suggestion`), `suggestionRef` and `via`. It allows not_connected when `ncReason` is given. Errors: 409 with `allowed` (refused by the graph); 422 with `needs` (missing input). `MoveView` gains `stageAt` and `meetingId`. Old bodies behave as today on permissive templates. |
| `POST /leads/{id}/dispose` (`Disposition`, `contracts.py:464`) | `stage` also accepts `junk` (a connected call with a wrong person). Adds `outcomeReason`, `reasonNote`, `meeting`, `suggestionRef` and `contact`. Writes `result` plus a `stage` event. |
| `POST /leads/{id}/reopen` (new) | `{commandId, expectedRevision, step?, nextActionAt, note?}` |
| `GET /leads/{id}` (`LeadDetail`) | Adds `moves[]`: allowed targets with `{step,label,kind,group,needs,reasons?}`. Also adds `meeting` (the open one), `suggestions[]` and `stageAt`. `LeadRow` adds `last_contact_at`, `latest` (one line), `stage_at`, `outcome_reason(_label)`, `next_action_note` and `no_next_action`. |
| `GET /leads` | New params: `step`, `source`, `due` (overdue, today, none, upcoming), `outcome` (won, lost, junk, open), `reason`, `sort` (next, age, last_contact, created, name) and `cursor` (keyset; `offset` is kept). `stage` also accepts `junk` and `closed`. `no_query` allow-list is updated. |
| `GET /board?pipeline&who&owner&source&due&q` (new) | `{pipeline, version, groups:[{group:active\|won\|lost\|junk, columns:[{step,label,kind,milestone,count,overdue,noNext,cards:LeadRow[≤25],nextCursor}]}]}`. Each lead appears once. |
| `GET /board/column?pipeline&step&cursor` (new) | The next page of one column |
| `POST /leads/bulk` | `action=stage` adds `reason` and `nextActionAt`. Leads refused by the guard are counted in `skipped` with a grouped `why`. |
| Meetings (new) | `POST /leads/{id}/meetings` (schedule; moves to the template's meeting stage when there is one) · `PATCH /meetings/{id}` (reschedule) · `POST /meetings/{id}/done {note, nextActionAt}` · `POST /meetings/{id}/missed\|cancel {step, ncReason?, nextActionAt, note}` · `GET /meetings?from&to&who` (agenda) |
| `GET /reports/pipeline?days&pipeline&owner&source` (new) | §7 |
| `GET /next-up?limit&pipeline` (new) | The ranked queue with `why`. `/next` returns its first item. |
| `GET /leads/{id}/suggestions` (new), `POST …/suggestions/{ref}/dismiss` | Replaces `/stage-suggestion`, which is kept and returns the stage-only subset |
| `GET/PUT /rules` (new, managers) | `{revision, rules}`. Audited. |
| `GET/PUT /journey`, `POST /journey/template` | Stages carry `moves/needs/reasons/rotHours`. The template call adds `map:{oldStep:newStep}` and `dryRun` (returns the counts that would move). |
| `GET /journey/morph`, `POST /journey/simulate`, `GET /journey/benchmarks` (new, L5) | §6 |
| `GET /duplicates`, `POST /duplicates/{id}/merge {survivorId, fields}`, `POST /duplicates/{id}/dismiss`, `POST /leads/{id}/unmerge` (new, L6) | §2.7 |

Every write carries `commandId` and `expectedRevision`, as today, so retries are idempotent and a stale revision gives 409.

## 5. Screens

All screens follow the same rules:
- Phone first (390 px), then 1440 px, in light and dark.
- Pressed state within 100 ms. Moves are optimistic, with Undo.
- Errors appear as a corner card and keep the last data on screen.
- Empty states are one line with one action. Loading uses skeleton cards.
- No price or cost is shown, and no customer names appear in code or fixtures.

| Screen | What's on it | 1-tap paths | Empty / loading / error |
|---|---|---|---|
| **Board, phone** (`leads/pipeline/board.tsx`, a "Board" view beside List) | Sticky stage strip: chips with counts, grouped **Active** · Won · Lost · Junk, with a red dot when a column has overdue leads. One column at a time, with horizontal swipe and scroll-snap. Cards sort: overdue → no next step → due today → later (Pipedrive pattern). **Card** (spec §8): name; masked phone ••4321 (full number on the lead); stage, implied by the column and shown in list and table; owner initials (managers); last contact ("Called 2 h ago"); next follow-up ("Today 5:00 pm · Call", red "Overdue 2 h", amber "No next step"); latest activity line; ageing dot; ✦ suggestion chip. | Tap the card to open the lead. Tap ✦ for the pre-filled sheet, then Confirm. Swipe right to call, left for WhatsApp (`gestures.ts`). Long-press for quick actions, including **Move to…** (allowed targets only). Drag a card onto a strip chip to move it. A move that needs nothing happens at once, with a corner card "Moved to … · Undo" (6 s). | "No leads in Meeting / Demo Scheduled." with one action. 3 skeleton cards while loading. Error: corner card plus Retry. |
| **Board, desktop** | Six active columns with their own windowed lists (25 per page plus "Show more"). On the right, a **closed rail**: Won, Lost and Junk drop zones with counts that expand on click. The column header shows the count and the overdue and no-next counts. | Dragging highlights the allowed columns and dims the rest, with a reason ("From New, book a meeting first"). Dropping on a column that needs input opens the sheet, with a ghost card until Save or Cancel. Keyboard: arrows, `M` opens Move, Enter opens the lead. | Same |
| **Stage-change sheet** (`stage-sheet.tsx`) | A "Move Asha to Meeting / Demo Scheduled" line with from→to. **Only the `needs` blocks:** meeting (date chips, time chips, mode Zoom / Google Meet / Phone / In person, link or location); next action (the `TimePicker` chips plus type); reason chips (Other opens a required note); a not-connected reason; note (optional). Final outcomes add one line: "Leaves follow-ups. You can reopen it." Filled from the suggestion, with "From the call: '…'". | When the suggestion is complete, the sheet shows only Confirm. The button says the action ("Book meeting", "Close as Lost", "Mark as Junk"). | 409 gives a corner card "Changed by a teammate, reloaded". 422 highlights the missing block. |
| **Meeting sheet** (`meeting-sheet.tsx`) | Schedule / reschedule, using the same blocks plus "Reminder 30 min before". The open meeting shows "Thu 5:00 pm · Zoom · Join" with **It happened**, **Reschedule**, **Missed** and **Cancelled**. It happened asks for a note and the next follow-up, then moves to Demo Completed. Missed and Cancelled ask "Where does it stand now?" (allowed targets only) plus the next action. An agenda appears in To call ("Meetings today"). | Join opens the link. Reschedule keeps history ("Moved from Thu 5 pm"). | "No meetings today". |
| **Timeline** (replaces `History` in `lead-sheet.tsx`) | A path strip across the top: "New 2 h → Not Connected 1 d → Interested 3 d → Meeting (now)". One stream by day, containing: stage moves (from→to, by, reason, source badge From call / Suggested / Rule / Import / Merged); calls with the stage folded in; WhatsApp and Meta messages; meetings (old→new time, done, missed); notes; assignments; "Came again via Meta lead form". Filter chips: All, Stages, Calls, Chats, Meetings, Notes. Closed leads show **Reopen**. | Reopen asks for the stage (default: where it was) and the next action. | "Nothing yet". Skeleton rows while loading. |
| **Table, desktop** (`leads-table.tsx`, `table-edit.tsx`) | Column picker: name, phone, stage, owner, source, next follow-up, last contact, attempts, age in stage, reason, city, interest, created. Server sort and filters (stage/step, owner, follow-up date, source, outcome, reason). Saved views (the existing local views plus the new filters). Keyboard as today. **Windowing** with our own fixed-row-height window and keyset pages of 200, so no new dependency or lockfile change. | Editing a stage cell runs the guard: it saves at once if nothing is needed, otherwise it opens the sheet anchored to the cell. Bulk "Move to Lost" asks for one reason for all. | Corner cards on error. A narrowed view offers "Clear filters". |
| **List, phone** (`list-view.tsx`) | Today's rows plus the spec card fields (last contact, next step, latest activity). The stage tabs gain Junk. | As today | As today |
| **Dashboard** (`leads/pipeline/dashboard.tsx`; placed in the hub with Liquid Glass) | KPI row: active leads, overdue, no next step, meetings today, won in the period. Current pipeline bar (each lead once; Active, Won, Lost and Junk). The four funnel conversions with medians. Lost reasons bar. Junk volume and junk rate by source. Per-seller table (active, overdue, no next, meetings, won, first response p50). Per-source table (leads, connect rate, junk rate, won). Period 7, 30 or 90 days. Sellers see "My" numbers. **Counts only, no money.** | Tapping any number opens the matching filtered list or board. | "Not enough data yet: 3 leads" until there are 10 or more leads |
| **Template builder** (`leads/journey/builder/*`; replaces the editor part of `journey-view.tsx`; ad platforms keep their own section) | Steps: **1 Pick** (industry cards, "Inside sales with demos", or "Keep my stages") → **2 Stages** (rename, add, archive, reorder, kind and meaning in plain words) → **3 Moves** (per stage, "From Interested you can go to …" toggles; required info per stage; reason lists) → **4 Rules** (plain-word switches, all off; §6) → **5 Preview** (30 fictional sample leads on a mini board, a "try a move" sandbox and simulator metrics) → **6 Done** (maps each old stage that has leads to a new stage, with counts, then saves **one** new version). | Every step has Next / Back. A draft is kept on the device until Done. | Validation in words from `journey.check`. |
| **Possible duplicates** (`leads/duplicates/*`, managers) | Pairs with reason chips ("Same email", "Same number, other format", "Similar name · same city") and a score. Side-by-side compare (fields, stage, owner, last activity). Survivor defaults to the more advanced stage, then the older lead. Field picks. | **Merge** (confirm; "Undo merge" in the timeline for 14 days). **Not duplicates** (remembered). | "No possible duplicates". |
| **Fixture** `/review-fixture/lead-pipeline` | Fictional names, all 9 columns, a meeting, a suggestion, overdue and no-next cases, plus junk and lost with reasons | — | Also used for the e2e tests and the tutorials |

## 6. Intelligence layer (offers only; a person confirms; no new AI calls)

### After-call proposal (`journey/suggest.py`)

It reads only facts the fast and deep pipelines already keep (`call_objects`). Per-seller AI levels (0119) and the spend guard therefore apply upstream, and nothing new leaves Sales X-Ray. It is not autonomous scoring (AGENTS guardrail). Only targets in the lead's `moves` are proposed.

| Existing signal | Proposal |
|---|---|
| `call_outcome=meeting_scheduled` plus `commitment.follow_up` with date and time | Meeting / Demo Scheduled at that time. Mode comes from the words (zoom, meet or google, visit or office, phone); otherwise the sheet asks. |
| `meeting_scheduled` with no time | Meeting / Demo Scheduled; the sheet asks for the date and time |
| `follow_up_agreed` / `callback_requested` plus a when | From New or NC: Interested with the next action at that time (purpose as the note). Otherwise the stage stays and only the next action is set. |
| `callback_requested` with talk under 90 s, or "busy/meeting/drive" words | Discussion Incomplete, to resume at that time (default "This evening") |
| `deal_closed` | Closed / Won (confirm) |
| `no_sale` plus the top unresolved objection | Closed / Lost. The reason follows the objection: price → price, competition → chose_other, timing → not_now, need → not_interested, authority → decided_not_to_proceed; otherwise not_interested. |
| `not_a_fit` | Closed / Lost: not_a_fit |
| A call inside the meeting window with ≥10 min of talk | Mark the meeting done, then Demo Completed |
| `signal.interest=high` on a New or NC lead with no outcome | Interested, next action tomorrow morning |

Calls never propose Junk. If the analysis is not ready when the sheet opens, the proposal arrives later as the ✦ chip on the card and the lead.

### Chat signals (`journey/chat_signals.py`)

Word lists in English, Hindi, Hinglish and Marathi, built like `ai_replies/rules.py`:
- "wrong number / galat number / maine enquiry nahi ki" → Junk? (someone_else or fake)
- Opt-out or "not interested / nahi chahiye" → Lost? (not_interested)
- "send details / brochure / price" → Interested plus a follow-up tomorrow
- The seller sent the `as_promised` template → Interested, if the lead is New or NC
- A time in the message ("kal shaam 6") → next action at that time
- Meeting words plus a time → a draft Meeting Scheduled

### "Who to call next" (`next_up.py`)

The queue is deterministic and explained.

**Strict tiers:**
1. A meeting starts within 30 min, or started less than 15 min ago with no outcome.
2. A missed inbound call that hasn't been called back (existing `call_back`).
3. A new lead inside its SLA window.
4. Overdue (more than 1 h late).
5. Due now, including retries.
6. Later today.

**Score within a tier:** `0.35·intent + 0.25·urgency + 0.20·stage + 0.10·freshness + 0.10·reachability`.

| Term | How it is computed |
|---|---|
| intent | `signal.interest` (high 1, medium .6, low .2, unknown .4). +.3 for an inbound reply or call in the last 48 h; −.2 if the last outcome was no_sale. Clamped to 0–1. |
| urgency | Tier 3: elapsed ÷ SLA. Otherwise min(1, minutes late ÷ 240). |
| stage | new .1, NC .1, DI .4, Interested .5, Meeting .7, Demo done .9 (by milestone) |
| freshness | exp(−days since last two-way contact ÷ 7); 0.5 if there was never contact |
| reachability | The team's connect rate at this hour over 30 days. ×0.5 after 6 or more attempts in 7 days. |

`why` = the largest term, in words ("Asked for a call at 5 pm", "Demo done 3 days ago"). Weights live in the rules config and are tuned with the simulator.

### Rules engine (`rules.py`)

Every rule is off by default unless marked, and audited.
- **Hard invariant:** no automatic rule may move a lead to Junk, and unanswered calls never trigger Lost or Junk on their own.
- On production, a rule that moves leads automatically also needs the owner's "approve data change" words (asked by the orchestrator).

| Rule | Params | Action |
|---|---|---|
| `first_response` | The existing `sla` settings | Alerts (exists) |
| `retry` (**on**, today's behaviour) | Spacing per NC reason, for example did_not_pick [1 h, 1 d], busy [30 m, 2 h], switched_off [3 h, 1 d]; none for the bad-number reasons | Sets next_action |
| `attempt_cap` | attempts N=6 within D=10 days | **Suggests** Lost: no_response |
| `junk_hint` | N=2 of switched_off, invalid_number, not_in_use or incoming_not_available (never did_not_pick or busy) | **Suggests** Junk (unreachable_verified or invalid_number). A `suggestion` event is logged, and the seller confirms. |
| `auto_message` | On arrival or on entering a stage: an approved WhatsApp template (the fake sender on dev) | Sends through the existing outbox |
| `meeting_reminder` (seller push **on**, prospect off) | Seller at T−30 min; the prospect through an approved template | Push or WhatsApp, once per `starts_at` |
| `idle_close` | days=30, min_attempts=6, to=lost:no_response | Moves the lead (`source=rule`, `rule_id`). Lost only. |
| `missed_call_autolog` | — | An unanswered outgoing call logged by the phone moves New to NC (`source=rule`) |

### Morph suggestions (`journey/morph.py`, on read, needs ≥30 moves in 90 days)

- **Unused stage:** no entries in 60 days → "Archive X?"
- **Parking lot:** median age in stage over 3× the pipeline median, with fewer than 10% of leads leaving per week → "Add a next-action rule, or split X"
- **Common skip:** 60% or more of exits from A skip B → "Make B optional, or reorder"
- **Backflow:** frequent C→B moves → "Is B after C?"
- **Missing stage:** the existing `signals.business_suggestions`
- **Reason drift:** "Other" over 25% of reasons, with recurring words → "Add reason 'X'"

One tap saves a new version (`origin=suggested`, with a note).

### Simulator and benchmarks (`journey/simulator.py`, pure and seeded)

- **Inputs:** the template version; the rules; arrivals per hour and source mix; sellers and their calls per hour; connect probability by attempt and hour; transition probabilities (from the org's history when it has 200 or more moves, else the template defaults); meeting show rate; 14 days of simulated time. Capped at 2,000 leads and about 2 s of CPU on demand, to protect the busy server.
- **Metrics:** first response p50/p90 and % within SLA; follow-up adherence (% of next actions done within 1 h of due); % active with no next action; overdue per seller-day; stage ageing p50/p90; the four conversions; junk rate.
- **Default targets:** first response p50 ≤ 5 min, adherence ≥ 90%, no-next-action 0%, overdue ≤ 5%. Runs are stored in `lead_desk_benchmark_runs`.

### Telemetry (coordinate with admin-2; counts only, no personal data, never canonical state)

`lead.stage_move{via,source,from_kind,to_kind,needs,ms_to_save}`, `lead.board_drag{result:moved|sheet|refused|undone}`, `lead.open_to_action_ms`, `lead.suggestion{action:shown|accepted|changed|dismissed,from}`.

## 7. Reports (`reports.py`, `GET /reports/pipeline`)

Every report has the same base set:
- the tenant, minus `test_data`, minus merged leads (L6);
- optionally narrowed to one pipeline, the current owner or a source;
- each count is over **distinct lead ids**.

| Report | Exact definition |
|---|---|
| Current counts per stage | `GROUP BY pipeline, stage, step` on leads, resolved through `Journey.resolve` (`lead_counts`, `model.py:199`). There is one row per lead, so each lead is counted once by construction, and the column totals equal the lead count (a test asserts this). |
| New → first connect | Denominator: leads created in the period, minus those **currently junk**. Numerator: those with a first connected contact (a `result` with connected=true, a phone-logged `call` with talk time > 0, an inbound reply, or a seller move into a contacted-or-later stage). Also reports the median minutes to first connect. |
| Interested → Meeting | Denominator: non-junk leads whose stage history first reached `qualified` **or any later funnel milestone** in the period (skipped stages count as passed). Numerator: those that have reached `appointment_booked` or later at any time since. |
| Meeting → Demo done | The same, `appointment_booked` → `appointment_done`. Also shows the meeting show rate: done ÷ (done + missed + cancelled) for meetings starting in the period. |
| Demo done → Won | The same, `appointment_done` → `won` |
| History source | `stage` events, plus legacy `result` events that change the stage and have no `stage_event_id`. A reopened lead counts each milestone once (its first time reaching it). Leads still in between are shown as "still open". |
| Lost reasons | Leads **currently** Lost, by `outcome_reason` (null shows as "Not recorded"), plus moves into Lost in the period by reason |
| Junk | Volume: leads currently Junk, and moves into Junk in the period. **Junk rate by source** = Junk ÷ all leads created in the period from that source, from the `meta` payload campaign or ad when present. It is fed to the ad engine as lead quality. |
| Overdue | Active (not won, lost or junk) leads with an owner and `next_action_at < now − 1 h` (`is_overdue`) |
| No next action | Active leads with `next_action_at IS NULL` and stage ≠ `new` (a new lead is due on arrival) |
| Per seller / per source | The rows above grouped by the current `owner_person_id` or by `source` + `source_label`. Conversions use the current owner. |

## 8. The 15 acceptance tests: where each is enforced and tested

The pytest file is `tests/database/test_lead_os_acceptance_postgresql.py` (L1); each test asserts the same lead id and a constant lead count. Vitest files are in `leads/pipeline/*.test.tsx` (L2–L3). The e2e test is `tests/e2e/workbench/test_lead_pipeline_browser.py`, run on the fixture and on dev (L7).

| # | Criterion | Enforced in | pytest | vitest / e2e |
|---|---|---|---|---|
| 1 | A new inquiry gives one record in New | `ingest` (stage `new`, `captured` event, unique phone) | `test_at01_*`: the same phone arrives in 3 formats from 2 sources, giving 1 lead, 1 captured event and 2 repeats | The board shows 1 card in New |
| 2 | Unanswered call → Not Connected | `dispose(connected=false)` → `stage_after_not_connected` → `_move` | `test_at02_*` | The after-call "No answer" path |
| 3 | Interest → Interested | `_move` with next_action required | `test_at03_*` (also: 422 lists `needs` when next_action is missing) | stage-sheet asks only for the next action |
| 4 | Interrupted → Discussion Incomplete | `_move` + resume time | `test_at04_*` | The board drag opens the sheet |
| 5 | Meeting booked → Meeting Scheduled | `_move` + `meetings.schedule`; unique scheduled meeting | `test_at05_*` (a reschedule updates the same row and keeps 2 meeting events) | meeting-sheet |
| 6 | Meeting happened → Demo Completed | `meetings.done` → `_move` | `test_at06_*` | "It happened" button |
| 7 | Deal closes → Won | `_move` + confirm; clears the next action | `test_at07_*` | Confirm sheet |
| 8 | Declines → Lost | `_move` + reason (other needs a note) | `test_at08_*` (missing reason gives 422) | Reason chips |
| 9 | Fake → Junk | `_move` + reason + confirm; excluded from the funnel | `test_at09_*` (junk is absent from conversion denominators) | Junk drop zone |
| 10 | Several unanswered calls do not make Junk | `stage_after_not_connected` never returns junk; the `rules.py` validator refuses an automatic junk rule | `test_at10_*`: 6 no-answers leave the lead in NC with no junk; with `junk_hint` on, 2× invalid_number gives a `suggestion` event and the stage stays NC | — |
| 11 | A stage change never duplicates the lead | Single writer; unique phone; repeat path | `test_at11_*`: every move plus a concurrent duplicate capture leaves `count(leads)` the same | — |
| 12 | Exactly one current stage | A single `stage` column; the board reads leads once | `test_at12_*`: board columns ∪ = leads with no overlap, and the counts sum to the lead count | The board fixture |
| 13 | History stays in the timeline | Append-only events; v2 `stage` events | `test_at13_*`: `detail.events` has every from/to, by, reason and source in order | timeline.test |
| 14 | Demo Completed stays during follow-up | `follow_up` on demo_completed (no move) | `test_at14_*`: the next action changes, no `stage` event is written, the count stays the same | — |
| 15 | Close, reopen and reassign keep history | `reopen`, `reassign` and `_move` never update old events | `test_at15_*`: the earlier events' ids and a data hash are unchanged; `outcome_reason` is cleared on reopen | e2e covers close, reopen and reassign |

Graph coverage: `tests/unit/lead_desk/test_transitions.py` is table-driven. Every pair in spec §3 is allowed, every other pair is refused, and each target asks for exactly its `needs`.

## 9. Phase plan (small commits; each with wb-ci green and screenshots at 390 and 1440 px)

| Phase | Commits (files) | Proof |
|---|---|---|
| **L1 Foundation** | 1) `journey/templates.py`, `vocabulary.py`: junk kind, `disqualified`, the `inside_sales_demos` template, reason lists. 2) Migration A (number from Align 3), `models.py` (`LeadMeeting`, the new columns and checks), backup parity (the infra scripts, coordinated) and the registry. 3) `journey/model.py` stage fields; `journey/transitions.py`. 4) `store.py` `_move` single writer used by `to_stage`, `dispose`, `_repeat`, bulk and import; the v2 event; reopen; `contracts.py` additions. 5) `meetings.py`, plus the meeting reminder in `push.py`. 6) `journey/http.py` and `http.py`: move, reopen, meetings, board, list filters, `LeadDetail.moves`. 7) The acceptance tests. | `test_transitions.py`, `test_lead_desk_lead_os_migration_postgresql.py`, `test_lead_desk_meetings_postgresql.py`, `test_lead_os_acceptance_postgresql.py` (15), the existing `test_lead_desk_*` and `test_journey*` suites green, parity test |
| **L2 Pipeline UI** | `leads/pipeline/{board,board-column,lead-card,stage-sheet,meeting-sheet,timeline,moves,pipeline-client}.tsx/.ts`; the "Board" view in `leads-page.tsx`; `History` replaced in `lead-sheet.tsx`; fixture `review-fixture/lead-pipeline/` | vitest: board, stage-sheet (asks only `needs`), meeting-sheet, timeline, moves (mirrors the server guard); 390 and 1440 screenshots, light and dark |
| **L3 Table + dashboard** | `leads-table.tsx` (columns, windowing, server sort), `table-edit.tsx` (stage through the guard), `lead-filters.tsx`, `saved-views.ts`, `leads/pipeline/dashboard.tsx`; backend `reports.py` plus `GET /reports/pipeline` | `test_lead_desk_pipeline_report_postgresql.py` (each lead once; junk excluded; legacy `result` events counted; reopen counted once); vitest for the table and dashboard |
| **L4 Builder** | `leads/journey/builder/*` and a slimmed `journey-view.tsx`; backend `PUT /journey` (moves, needs, reasons) and `POST /journey/template` with `map` and `dryRun` | `test_journey.py` additions (graph round-trip; old versions stay permissive); `builder.test.tsx` |
| **L5 Intelligence** | `journey/suggest.py`, `journey/chat_signals.py`, `next_up.py`, `rules.py`, `journey/morph.py`, `journey/simulator.py`; migration B; the ✦ chip and after-call proposal UI; the Rules step | Unit tests for each pure module (fact → proposal table; ranking order; the never-auto-junk invariant; seeded simulator metrics); audit row on every rules save |
| **L6 Duplicates** | Migration C; identities in `ingest`, `match` and the phone book; `duplicates.py` (sweep, merge, unmerge); `leads/duplicates/*` | `test_lead_desk_duplicates_postgresql.py` (exact match attaches; fuzzy match makes a pair; merge then unmerge round-trips; merged leads are hidden everywhere through `_visible`) |
| **L7 QA** | vitest and e2e for the 15 tests; one Redmi pass through the orchestrator (one phone driver); the sales lead tries it on dev; fixture routes sent to the tutorials session | `test_lead_pipeline_browser.py` on the fixture and on dev |

## 10. Owner decisions, production data changes and coordination

**Owner or sales-lead decisions:**
1. The template name "Inside sales with demos".
2. The three extra lost reasons (price, not now, not a fit).
3. A **Won** lead that enquires again: keep it Won with "came again" plus a task (recommended), or reopen it to New as today.
4. Who may reopen a Won lead, and who may reclassify to Junk (proposed: owner and admin only).
5. Whether the seller's meeting reminder push is on by default (proposed: on; the prospect reminder stays off).

**Production data changes** (each needs the owner's "approve data change" words, asked by the orchestrator):
- Installing the template for AC on production, including the mapping of old Follow-up and Interested leads (dry-run counts shown first).
- Merging AC's existing duplicates (the read-only list is shown first; a `scripts/data-changes/` script only if the app path isn't enough).
- Switching on `idle_close` or `missed_call_autolog` on production.

**Coordination:**
- **Align 3:** the three migration numbers, and the backup-parity edits to the infra scripts.
- **partner_events owner:** read `stage` events, add `junk`, announce it in the developer docs.
- **Connectors owner:** `disqualified` mapping, and the junk rate to the ad engine.
- **WhatsApp and chats (shared):** chat signals are read-only; auto messages go through the existing outbox.
- **Liquid Glass:** the hub placement of the dashboard and builder.
- **Builder:** the shell and tap feedback.
- **admin-2:** the telemetry events in §6.

## 11. Changes made while building L1 (24 Oct 2026)

These refine §2.3 and §2.4. Each keeps the design's rule of one record, one current stage and one history entry per move.

- **A call that moves a lead writes one event, not two.** `dispose` keeps writing its `result` event, and when the call changes the stage the same event also carries the v2 move fields (`v`, `action`, `from_kind`, `to_kind`, labels, `source`, `via`, `contact`). No second `stage` event is written, so `stage_event_id` is not needed.
  - Why: the ad engine, partner webhooks, `performance()`, My day, call-back and SLA all read `result` events today. A second event per move would need a skip rule in each of them.
  - The history of moves is therefore: `stage` events, plus `result` events whose stage changed. The reports reader (L3) reads both.
- **The Lost or Junk reason is `outcome_reason`, not `reason`.** In `result` events `reason` already means why a call didn't connect, and the timeline, SLA and reports read it that way. The v2 keys are `outcome_reason`, `outcome_reason_label` and `reason_note`. A move into Not Connected from the board keeps `reason` for the not-connected reason, the same as a call.
- **Only what the server must have is a need.** `needs` are refused with 422 when missing: `next_action`, `meeting`, `reason`, `nc_reason`, and `reason_note` when the reason is Other. Confirm and the optional note are `asks`: the sheet shows them, the server never requires them. This keeps today's after-call Won and Lost working for every list without moves.
- **Lists without moves.** Junk always needs a reason, and Couldn't reach always needs a not-connected reason (the board could not move a lead there before). Nothing else is required, and anyone who works the lead may move it anywhere, as today.
- **Who may.** Reopening Won is for owners and admins only in a list with moves. Turning a Won or Lost lead into Junk is for owners and admins in every list.
- **An unanswered call never reopens a closed lead.** `stage_after_not_connected` now keeps Won, Lost and Junk where they are. Before, an unanswered call on a Won or Lost lead moved it to Not connected.
- **Every list can mark Junk.** A list without a Junk stage uses the desk's own (`model.JUNK`, key `junk`), and the board always shows it.
