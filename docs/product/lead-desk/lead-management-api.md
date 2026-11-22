# Lead management API (Archive and Bin, bulk with undo, seller load, saved views, tags, outreach)

The owner, 16 Nov 2026: "management of leads and reorganizing, reassigning each other, deleting
old leads, managing the leads at a higher level is not there". Design study:
`docs/design/research/lead-import-and-management-20261116/02-management-findings-and-spec.md`
(§4, M1–M6, §6). The owner picked the screens on 17 Nov (M2-A laptop table, M1 phone selection,
M1-C assign with seller load, M3-A clean-up, M3-B bulk change, M4-A by seller, M4-B saved views).
This page is the server side those screens call. All routes are under `/v1/lead-desk`, need a
Sales Xray session in an organisation workspace, and writes need the Sales Xray origin. Every
read and write is scoped to the caller's workspace; sellers only ever reach their own leads.
Web client types: `apps/sales-xray-web/app/leads/leads-client.ts`.

## 1. Archive and Bin (`lead_desk/shelf.py`, migration 0158)

| Route | Who | Body | Answer |
|---|---|---|---|
| `POST /leads/archive` | owners, admins, managers | `{command_id, lead_ids[1..2000]}` | `LeadsShelved` |
| `POST /leads/bin` | owners, admins | same | `LeadsShelved` |
| `POST /leads/restore` | Archived: owners, admins, managers. Bin: owners, admins | `{command_id, lead_ids, from: "archive" \| "bin"}` | `LeadsShelved` |
| `POST /leads/purge` | owners, admins | `{command_id, lead_ids[1..500]}` | `LeadsDeleted` |
| `GET /leads?shelf=archived` | everyone (their own leads; the team for those who see it) | the usual list options | `LeadPage` |
| `GET /leads?shelf=bin` | owners, admins | the usual list options | `LeadPage` |

`LeadsShelved` = `{action, changed, unchanged, not_found, lead_ids}`: `lead_ids` are the leads
that moved, in the order asked; `unchanged` were already there; `not_found` are not in this
workspace (or not the caller's).

- **Archive:** the lead leaves every work list, tab count, badge, queue, timer and push
  (`history.on_desk`, folded into `worked()`, `inbound_only()` and `on_side()`). It keeps stage,
  owner, follow-ups and history. A search still finds it; rows carry `archived_at`.
- **Bin (Delete):** the lead is in no list but the Bin, not even a search's, and no page or
  write opens it (404). Binning an archived lead keeps it archived, so Restore from the Bin puts
  it back where it was.
- **Purge:** `POST /leads/purge` deletes Bin leads for good now; a lead not in the Bin is counted
  in `not_found` and left alone. The API process also purges every lead in the Bin for more than
  30 days, hourly (`shelf.purge_due`). Both are the old hard delete (`deletion.py`): the same
  removals and the same `lead_desk.leads.deleted` audit event; the job's is `actor_type
  "system"`, `payload.by = "lead_desk.bin_purge"`.
- **Coming back by itself:** a person who enquires again (an ad's or a website's form; never a
  file, a sheet or a hand-added row) brings an archived or binned lead back to the desk; the
  repeat event says `from_shelf`.
- **Audit and history:** one audit event per request (`lead_desk.leads.archived`, `.binned`,
  `.unarchived`, `.restored`; resource `lead_desk.lead_shelf`, id = `command_id`; ids and counts
  only), which is also the idempotency record: a retry returns the first answer. Each lead gets
  an `edited` event whose view has `shelf` set and the words in `allocation_reason`.
- `POST /leads/delete` (the 21 Oct hard delete) still works unchanged for owners and admins.
  The new screens should send Delete to `/leads/bin` and use `/leads/purge` from the Bin only.
- Merged leads: a lead merged away keeps pointing at the lead it was merged into; if that lead is
  binned, opening the merged one finds nothing until it is restored (duplicates.md).

## 2. Bulk changes on a frozen selection, with Undo (`lead_desk/bulk_jobs.py`)

| Route | Who | Answer |
|---|---|---|
| `POST /leads/bulk-jobs` | owners, admins, managers (Bin and restore from it: owners, admins) | `BulkJob` |
| `POST /leads/bulk-jobs/{job_id}/undo` (empty body) | the same as the job's action | `BulkUndone` |
| `GET /leads/bulk-jobs?limit=20` | owners, admins, managers | `{jobs: BulkJob[]}`, newest first |
| `GET /leads/bulk-jobs/{job_id}` | owners, admins, managers | `BulkJob` |

Request: `{command_id, lead_ids | filter, expected_total?, action, person_id?, step?, pipeline?,
outcome_reason?, reason_note?, next_action_at?}`.

- **Selection:** `lead_ids` (up to 2,000), or `filter`, the same options as `GET /leads`
  (`scope`, `side`, `view`, `stage`, `step`, `search`, `owner`, `pipeline`, `source`, `due`,
  `contact`, `created`, `when`, `since`, `until`, `test`, `older`, `duplicates`, `shelf`). The
  filter is frozen when the request arrives: the leads matching then are the selection. More
  than 2,000 matching is refused (422, "N leads match. Up to 2,000 at a time."). Send
  `expected_total` (the "Select all 522" number) to get 409 "The list changed: N leads match
  now" instead of acting on a different set.
- **Actions:** `assign` (`person_id`, or none for the lead rules), `stage` (`step`, plus
  `outcome_reason` / `next_action_at` when the move asks), `pipeline`, `archive`, `bin`,
  `restore_archive`, `restore_bin`. Each lead changes as its own action would (store `bulk`,
  shelf `move`), with its own history line; a lead that can't change is counted in `unchanged`
  and grouped in `failed[{reason, count}]`. Tags are not offered: leads have no tags yet.
- **Answer:** `BulkJob = {job_id (= command_id), action, selection: "ids" | "filter", selected,
  changed, unchanged, not_found, failed, lead_ids (changed, in the order asked), words,
  by_person_id, at, undo_until, undoable, undone_at}`. A retry with the same `command_id` returns
  the same job.
- **Undo:** for 30 minutes (`undo_until`), once per job. Every changed lead whose revision is
  still the one the job left goes back to what it was (owner and hand-over time; stage, step,
  stage time, follow-up, reason and pipeline; archived or binned). A lead changed since is left
  as it is and counted in `skipped`. Stage news the undone move queued and nobody sent yet is
  dropped; news already sent to an ad platform or partner stays sent. Tasks a stage move closed
  are not reopened.
- **History and audit:** each lead's history line for the change keeps `bulk_job` and
  `bulk_before` (what Undo restores); the undo is a new `edited` line naming it. The job is one
  audit event `lead_desk.bulk_job.applied` (resource `lead_desk.bulk_job`, id = job id; ids,
  counts and revisions; a filter's search words are kept only as `true`), the undo one more
  (`lead_desk.bulk_job.undone`, id `undo:<job id>`).
- The older `POST /leads/bulk` (ids, up to 500, no undo) still works for today's screens.

## 3. Seller load (`lead_desk/load.py`)

`GET /team/load?side=inbound|cold` (owners, admins, managers, viewers; sellers 403) →
`SellerLoads = {side, generated_at, sellers[], unassigned, totals}`; each seller is
`{person_id, name, role, takes_new_leads, max_open, load}` and each `load` is
`{open, late, due_today, untouched_7d, by_stage{stage: n}}`.

- **open:** leads in the six working stages on that side, never history, archived or binned.
- **late:** open leads more than an hour past their follow-up, or new leads past their first hour
  (the badge's and the rows' rule). **due_today:** follow-up today (India time), not late.
  **untouched_7d:** no contact for 7 days and in the desk for 7 days or more.
- The counts are one grouped read; people come from the team list (whether they take new leads,
  their limit). Someone who holds open leads but no longer works them still has a row
  (`role: null`), so the numbers add up: per-seller stages = their `open`, sellers +
  `unassigned` = `totals`.
- The assign sheet's "after: N" is the screen's own sum (`open` + the leads it is giving).

## 4. Saved views (`lead_desk/saved_views.py`, migration 0159)

| Route | Who | Answer |
|---|---|---|
| `GET /views?counts=true` | everyone | `{views: SavedView[]}`: the team's, then mine |
| `POST /views` | everyone ("me"); owners, admins, managers ("team") | `SavedView` (201) |
| `PUT /views/{view_id}` | the view's owner ("me"); owners, admins, managers ("team") | `SavedView` |
| `POST /views/{view_id}/delete` | the same | `{views}` |

- Create: `{command_id, name (1–40), visibility: "me" | "team", filter, display}`; `filter` is
  the bulk change's `LeadFilter` (the GET /leads options), `display` the screen's own JSON
  (columns, density, sort; up to 4,000 bytes). Idempotent by `command_id`; a name already used in
  the same place is 409; up to 40 views per person and 40 team views.
- Edit: `{expected_revision, name?, visibility?, filter?, display?, position?}`; a stale
  revision is 409. Delete: `{expected_revision}`; the view is removed (a preference, not history).
- `SavedView = {view_id, name, visibility, owner_person_id, mine, can_change, filter, display,
  position, revision, count, created_at, updated_at}`. `count` (only with `counts=true`) is the
  list's own total for the person asking; null when their role can't open that list.
- A person never sees someone else's "me" views. The phone's on-device views
  (`app/leads/saved-views.ts`) are untouched; the UI task moves them here.
- Starter views (spec §4.6) are the screen's presets, made from the same filters: Unassigned
  (`scope: "unassigned"`), Late follow-ups (`due: "late"`), Not worked for 30 days
  (`contact: "never"` or an older `contact`), Possible duplicates (`duplicates: true`), Archived
  (`shelf: "archived"`).

## 5. Tags (`lead_desk/tags.py`, migration 0165, v1.94)

The workspace's own short labels ("Nov video ad", "Hot"), each with one of the app's colours
(`mint, sky, amber, rose, violet, slate, lime, orange`; a database CHECK holds them). One name
per workspace, case aside: a unique index on `(tenant_id, lower(name))`.

| Route | Who | Answer |
|---|---|---|
| `GET /tags` | everyone | `{tags: TagView[]}` in the workspace's order |
| `POST /tags` | everyone | `TagView` (201) |
| `PUT /tags/{tag_id}` | owners, admins, managers | `TagView` |
| `POST /tags/{tag_id}/delete` | owners, admins, managers | `{tags}` |
| `POST /leads/{lead_id}/tags` | anyone who may change the lead | `{lead_id, tags: TagChip[], added, removed}` |

- Create: `{command_id, name (1–32), colour?}`. Idempotent by `command_id`, and a name already
  here (case and spaces aside) is that tag, so a twin tap never makes two, even at the same
  moment (the unique index decides; the loser gets the winner's tag). Up to 100 per workspace;
  with no colour, the next one round the list.
- Edit: `{expected_revision, name?, colour?, position?}`; stale is 409, a name taken is 409.
  Delete: `{expected_revision}`; the tag leaves every lead. Each lead's history keeps the lines
  that added it.
- Audit: `lead_desk.tag.created` (colour, position), `lead_desk.tag.edited` (which fields
  changed, new revision) and `lead_desk.tag.deleted` (lead count). Ids only, never the name.
- One lead: `{command_id, add: tag_id[], remove: tag_id[], new: name[] (up to 3)}`; `new` makes a
  tag by name on the way. Up to 10 tags on a lead: asking for an 11th is 422 ("Up to 10 tags on a
  lead; take one off first."), and nothing changes. Each change is one `edited` history line with
  `changed: ["tags"]` and `allocation_reason` like "Tag added: Hot" or "Tags removed: A, B".
- `TagView = {tag_id, name, colour, position, revision, leads, can_change}`; `leads` counts the
  leads on the desk carrying it that the person may see. `TagChip = {tag_id, name, colour}`.
- Every lead row (`LeadRow.tags`) and the lead page carry their chips in the workspace's order.
- Filter: `GET /leads?tag=<tag_id>`; `LeadFilter.tag` in saved views and bulk "all matching".
- Bulk: `POST /leads/bulk-jobs` with `action: "tag" | "untag"` and `tag_ids` (1–10). Owners,
  admins and managers. A lead that already had (or lacked) the tag is `unchanged`. Words: "2 leads
  tagged Hot", "Hot taken off 3 leads". A lead that would pass 10 tags stays as it is and is in
  `failed` as "10 tags already". Undo (30 minutes) reverses exactly what the job changed on each
  lead (a lead that has 10 tags since is skipped); the lead's revision does not move for a tag.
- Merge: the merged-away lead's tags go on the kept lead too, as many as fit, in the workspace's
  order; an unmerge takes off exactly those.
- Not yet: tags on import (I4). Undo import treats the import's own history lines as not work, and
  an import's tag line could not yet be told apart from a later import's edit of the same lead.

## 6. Outreach: the touch log, the counter and the guard (`lead_desk/outreach.py`, migration 0166, v1.95)

The owner, 22 Nov 2026: "every person we contact is a lead, every message we send them is
tracked, so we never feel spammy". Spec: `boards/sx-redesign/review/v195-outreach-log-spec.md`.
A **touch** is one message, call, file or quote we send a lead. Each keeps exactly one line in the
lead's history (`message`, `email` or `call`); its row in `lead_desk_touches` holds who sent it,
our own short summary (never the lead's words), the provider and its delivery state, the reply
that answered it, whether it counted, and the guard's verdict when it went.

Touches are written by: a ready message (`POST /leads/{id}/messages`: `via app_link`, status
`opened`), a Cloud API WhatsApp (`via cloud`, linked to the message row; the webhook copies its
delivery state), the Call button and the phone's own call log (`channel call`), Log a touch, and
outside senders through the API below. An inbound WhatsApp, or a reply an outside sender reports,
answers the newest unanswered touch on that channel in the 7 days before it.

**The guard** (ok, warn or block, the same shape everywhere): a STOP on the channel blocks and
nothing overrides it; a lead in the Bin blocks (test data blocks automations, warns people);
archived and history leads warn; the lead wrote in the last 24 hours on this channel: ok and not
counted; then the day limit (in India's day), the week limit (rolling 7 × 24 h) and the cool-off
(that many unanswered in a row, then rest days), each in the channel's mode; outside the sending
hours people are warned and automations held; a manager's unused override passes warn or block
once. WhatsApp, SMS, email, Messenger, Instagram, files and quotes count together; calls and
in-person hand-overs count only when their mode is warn or block.

| Route | Who | Answer |
|---|---|---|
| `GET /leads/{lead_id}/outreach?channel=` | anyone who can open the lead | `OutreachGuard` (default channel: WhatsApp with a phone, else email) |
| `GET /leads/{lead_id}/touches?cursor=` | the same | `{touches: TouchView[], next_cursor}` newest first, 50 a page |
| `POST /leads/{lead_id}/touches` | the lead's owner, managers | `{touch: TouchView, outreach: OutreachGuard}` (201) |
| `POST /leads/{lead_id}/overrides` | owners, admins, managers | `OverrideView` (201) |
| `POST /outreach/guard` | owners, admins, managers | `BulkGuard` for up to 500 leads |
| `GET /outreach/rules` | everyone | `OutreachRules` |
| `PUT /outreach/rules` | owners, admins, managers | `OutreachRules` |
| `GET /outreach/senders` | owners, admins | `{senders: SenderView[]}` |
| `POST /outreach/senders` | owners, admins | `SenderView` (201) |
| `PUT /outreach/senders/{sender_id}` | owners, admins | `SenderView` |
| `POST /outreach/senders/{sender_id}/pause` | owners, admins | `SenderView` (`{expected_revision, paused}`) |

- `OutreachGuard = {lead_id, would_create, channel, mode, verdict: ok|warn|block, reasons:
  [{code, words, level: show|warn|block}], words, last_touch_at, counts: {today, week,
  unanswered, calls_week}, next_ok_at, quiet_until, opted_out, in_reply_window, override:
  {possible, who}, override_id, reservation_id}`. `words` is the counter line: "Not contacted
  yet", "Touched today at 11:02 · 2 touches this week", "Last touched 2 days ago · 3 touches this
  week · 2 calls". Reason codes: `opted_out`, `opted_out_other` (show), `in_bin`, `test_data`,
  `archived`, `history`, `internal` (show), `day_cap`, `week_cap`, `rest` ("3 touches with no
  answer: rests until Thu 27 Nov"), `quiet`.
- The lead page (`LeadDetail.outreach`) carries the guard for the lead's main channel, and each
  history line that is a touch carries `LeadEventView.touch: TouchView = {touch_id, lead_id,
  channel, content_kind, initiated: outreach|reply, sender_type: person|automation, by_name,
  person_id, sender_id, sender_label, automation, via, provider, summary, template_name,
  attachment, status, status_at, sent_at, counted, verdict, after_block, override_by_name,
  override_reason, replied_at, event_id}`.
- Log a touch: `{command_id, channel, via: manual|app_link, content_kind?, summary? (≤ 280),
  attachment?: {kind, name, bytes?}, sent_at?, override_id?}`. Idempotent by `command_id`. A STOP
  on that channel is 409.
- Sends from the app ask first: a ready message or a seller's WhatsApp is refused with 409
  ("Held by the outreach limits: …") on a block (a STOP always; a limit only when the channel's
  people mode is block). Campaign steps are held while the guard says warn or block (they wait for
  `next_ok_at` or the sending hours, or are skipped with `outreach_limit` when waiting can't
  help), once the workspace has saved its limits; first and after-hours replies are recorded, not
  held.
- Override: `{command_id, channel, reason_key: lead_asked|time_sensitive|wrong_count|other,
  reason_text? (required for other)}`; 30 minutes, one touch. 409 when nothing holds the send or
  the lead said STOP. `OverrideView = {override_id, lead_id, channel, reason_key, reason_text,
  granted_by_name, expires_at, used_at, guard}`.
- Rules: `{expected_revision, enabled?, per_day? (1–10), per_week? (1–30), rest_after? (0–20),
  rest_days? (1–90), quiet?: {days, start, end} | null, modes?: {channel: off|show|warn|block |
  {people, automations}}, keep_reply_words?, never_lead?: (≤ 200 phones or emails)}`; stale is 409.
  `OutreachRules` adds `hours_in_use` and `can_edit`. Defaults: 1 a day, 3 a week, rest 14 days
  after 3 unanswered, WhatsApp warn for people and block for automations, SMS/email/Messenger/
  Instagram warn, calls show, sending hours = the work hours or 10:00–20:00 Mon–Sat.
- Bulk: `{lead_ids (≤ 500), channel, sender: person|automation}` → `{channel, ok, warned, held,
  said_stop, words: "38 ok · 4 warned · 6 held (3 said stop)", leads: [{lead_id, verdict,
  opted_out, words, next_ok_at}]}`.
- Senders: `{command_id, key (a-z0-9-), label, kind: automation|person_tool, person_id (a person's
  tool only), api_key_id (a key with outreach:write), channels, lead_defaults: {create, side:
  live|cold, tags (≤ 3), assign: rules|none}, guard_mode: report|hold}`.
- Audit (ids, counts and field names only): `lead_desk.outreach.settings_changed`,
  `.sender_created`, `.sender_changed`, `.sender_paused`, `.sender_key_bound`,
  `.override_granted`, `.override_used`, `.sent_past_block`.
- Delete removes a lead's touches, replies and overrides with it; a merge moves touches and
  replies to the kept lead.

### The Outreach view (v1.95.3): `GET /outreach`

"What the owner sent". Query: `view=leads|touches` (default leads), `by=person:<id>|person:me|
sender:<id>|automation:<rule>`, `channel=`, `from=` and `to=` (team days, YYYY-MM-DD; default the
last 7 days; up to 92 days), `replied=any|replied|no_reply`, `over=true` (the guard warned or
blocked it), `cursor=`, `limit=` (1–100, default 50). Owners, admins, managers and viewers see the
team, outside senders included; a seller sees their own sends and the leads they added (any other
`by` is 403; `filter.locked_to_self` is true); finance is 403.

`OutreachPage = {filter: {view, by, channel, date_from, date_to, replied, over, locked_to_self},
hero: {touches, leads, replied, past_limit, leads_added (by=person only), period ("Today", "Last
7 days", "1 Nov - 20 Nov 2026"), words ("142 touches · 38 leads · 9 replied"), sentence ("6 were
sent past a limit." / "None went past a limit.")}, leads: OutreachLeadRow[], touches: TouchView[],
next_cursor}`. By lead (`leads`, newest activity first): each lead touched in the filter, plus,
for `by=person:`, the leads that person added in the period: `{lead_id, name,
added_by_person_id, added_by_name (the person, else the source label such as "sx-engage"),
added_at, touches, last_touch_at, replied, received: TouchView[] (oldest first, up to 20)}`. By
message (`touches`): every touch, newest first. Leads in the Bin and unused reservations never
show.

### The ingest API for outside senders (`integrations/outreach_api.py`, under `/v1/api/outreach`)

An organisation API key with `outreach:write` / `outreach:read` (key-only scopes; a connected app
is `org_key_only`). Every write names `sender`: a sender of this workspace bound to this key.
Errors are `{error: {code, message}}`: 401 `key_invalid`; 403 `scope_missing`, `org_key_only`,
`sender_not_bound`, `sender_paused`, `channel_not_allowed`; 404 `reservation_not_found`; 409
`idempotency_mismatch`, `reservation_used`; 422 `needs_id`, `phone_needed` (an `@lid` alone),
`bad_phone`, `bad_time` (no zone, or more than 5 minutes ahead), `summary_too_long`, `bad_by`;
429 `rate_limited` (600 a minute per key, after the plan's own per-key limit).

| Route | Scope | Body → answer |
|---|---|---|
| `POST /check` | write | `{sender, to: {phone?, email?, name?}, channel, hold?, client_ref?}` → `OutreachGuard` (with `reservation_id` when held for 15 minutes), or `{ignored: "internal"}` |
| `POST /touches` | write | spec §3.2 body → 201 `{touch_id, lead_id, lead_created, duplicate: false, counted, after_block, guard}`; a repeat 200 `{…, duplicate: true}`; `{ignored: "internal"}`; `{lead_id: null, stored: false}` |
| `DELETE /reservations/{id}` | write | `{reservation_id, released}` |
| `POST /statuses` | write | `{sender, statuses: [{provider, provider_message_id, provider_chat_id?, status, at, error_code?}] (≤ 100)}` → `{updated, ignored, unknown}` |
| `POST /replies` | write | `{sender, provider, provider_message_id, provider_chat_id?, channel, from, at, kind, excerpt?, opt_out?, in_reply_to?, lead?}` → 201 `{reply_id, lead_id, lead_created, duplicate, touch_id, opted_out}`; a reaction is `{ignored: "reaction"}` |
| `POST /opt-outs` | write | `{sender, to, channel, at?}` → `{lead_id, recorded, channel}` |
| `GET /opt-outs?since=` | read | `{opt_outs: [{lead_id, channel, phone, email, at}], next_since}` |
| `GET /touches?phone=|email=|lead_id=&since=&cursor=` | read | `{lead_id, touches: […], next_cursor}` |

Leads match by phone (E.164 with the workspace's default country; a WhatsApp JID's number is
read), then email (any case); a merged lead resolves to its survivor; teammates and the Never a
lead list are ignored. A new lead (when `lead.create` or the sender's default says so) is made by
the desk's own intake: source `webhook`, source label the sender's label, the side and up to 3
tags, created by the sender's person for a person's own tool. Not yet: the backfill of old
messages, the "Ask a manager" request, the bell line for a send past a block, Messenger and
Instagram sends as touches, and WhatsApp Business app echoes as touches.
