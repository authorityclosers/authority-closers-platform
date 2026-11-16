# Lead management API (Archive and Bin, bulk with undo, seller load, saved views)

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
