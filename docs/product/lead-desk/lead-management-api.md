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
