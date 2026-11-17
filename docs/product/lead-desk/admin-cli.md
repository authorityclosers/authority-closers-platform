# The admin CLI (17 Nov 2026)

The owner asked for "a hardcore admin CLI for administration of the entire sales cycle": every base-level primitive,
not just adding people. `scripts/data-changes/admin.py` is that CLI. Each command goes through the app's own
service (OrganisationService, LeadDesk, the bulk jobs, Archive and Bin, the AI-apps switch, the file import), so a
change made here is the same change the app makes, with the same history lines and checks.

It is an owner-approved data change tool (AGENTS.md, "OWNER-APPROVED DATA CHANGES"). Production runs belong to the
orchestrator.

## Running it

```sh
# Production (the orchestrator): inside the API container, the script on stdin
docker exec -i ac-application-production-api-1 python - people set-role \
  --environment production --allow-production --tenant-id <workspace> --person-id <person> --role admin \
  --actor-person-id <operator person> --approver <ref> --issue <ref> \
  [--apply --snapshot-reference <snapshot ref>] < scripts/data-changes/admin.py

# Dev: in the LIVE API slot (live-backend/a or /b; find it with ps), with the dev settings
sudo systemd-run --quiet --wait --pipe --collect \
  -p EnvironmentFile=/etc/authority-closers/development/api-live.env \
  /srv/authority-closers/development/live-backend/<slot>/.venv/bin/python -I admin.py \
  workspaces list --environment development
```

`leads import` loads `import-leads-file.py` from beside `admin.py`, so it needs both files on disk (it can't run from
stdin; run the importer directly there).

## Rules every command follows

- **Dry run by default.** A changing command makes the whole change inside its transaction, prints before and after,
  and rolls it back. `--apply` commits once.
- **Named approval.** `--actor-person-id` (the operator's person), `--approver` and `--issue` are required for every
  change. References are short ids, never personal data.
- **One audit event** per applied change: `admin.data_change_applied`, naming the approver, the issue, the operator,
  the run and the command's intent. A change that finds nothing to do (`already_admin`, `no_leads`, `unchanged`) is
  recorded the same way, so a retry of its command id replays it rather than acting later.
- **A rerun changes nothing.** The command id defaults to one derived from the environment, the issue and the
  command's intent, so running the same command again returns `replayed`. Pass `--command-id <uuid>` for a fresh run
  of the same change (for example, turning a switch on again later under the same issue). A used command id with a
  different change is refused.
- **Snapshots.** Staging and production need `--snapshot-reference` to apply; production also needs
  `--allow-production` and the container's own production settings. Development needs neither.
- **Reads** (`list`, `show`, `switches` with no flag) run in a read-only transaction and write nothing.
- **Output.** Plain lines by default; `--json` prints the receipt as JSON. The five first commands' flat names still
  work and always print JSON.
- **Privacy.** Ids, roles and display names only. E-mails are masked (`a***@example.com`). A lead's name shows only
  with `leads list --names`; a phone number or e-mail never.
- Protected tenants (operations, the public learner tenant) are refused.

## Commands

### People (`--tenant-id`)

| Command                                  | What it does                                                                                                | Service                                               |
| ---------------------------------------- | ----------------------------------------------------------------------------------------------------------- | ----------------------------------------------------- |
| `people list`                            | members (role, status) and pending invites                                                                  | read                                                  |
| `people show --person-id P`              | one member: role, verified e-mail, open leads                                                               | read                                                  |
| `people invite --email E [--role R]`     | a verified account joins at once; anyone else gets the invitation e-mail; a pending invite isn't sent twice | `add_member`, `request_member(operator_auto_join)`    |
| `people resend-invite --email E`         | revokes the pending invite and sends a new one (the app has no resend)                                      | `revoke_invite`, `request_member`                     |
| `people set-role --person-id P --role R` | admin, manager, member, viewer or finance; never the owner                                                  | `change_member_role`                                  |
| `people transfer-owner --person-id P`    | P owns; the old owner becomes an admin; both e-mailed                                                       | `transfer_ownership`                                  |
| `people rename --person-id P --name N`   | the account's display name                                                                                  | direct (the app lets a person rename only themselves) |
| `people remove-member --person-id P`     | the membership ends; never the owner                                                                        | `remove_member`                                       |

`people taking-leads --person-id P --taking on|off` is Team's "Taking new leads" switch (`save_rep`, only the switch
changes; P's open leads stay). Off, the lead rules skip P, so new leads wait unassigned for a manager.

Old names: `set-role`, `transfer-owner`, `rename-person`, `remove-member`.

### Workspaces

| Command                                                                                                  | What it does                                                                   | Service                                     |
| -------------------------------------------------------------------------------------------------------- | ------------------------------------------------------------------------------ | ------------------------------------------- |
| `workspaces list`                                                                                        | every organisation: name, status, members                                      | read                                        |
| `workspaces show --tenant-id T`                                                                          | owner, members by role, invites, domains, the AI-apps switch, lead counts      | read                                        |
| `workspaces create --name N --owner-person-id P`                                                         | a new organisation owned by P (a verified account)                             | `OrganisationService.create`                |
| `workspaces rename --tenant-id T --name N`                                                               | the organisation's name (2 to 80 characters)                                   | the settings field, locked as Settings does |
| `workspaces domains --tenant-id T --domain D [...] [--auto-join]` / `--clear`                            | the verified e-mail domains, attested by the operator; the full list each time | `set_domains_attested`                      |
| `workspaces switches --tenant-id T [--paused on/off] [--note] [--task] [--outcome] [--update] [--stage]` | the AI-apps switch (Organisation → AI apps); no flag shows it                  | `AiWrites.save_settings`                    |

Sales X-Ray itself has no switch: it is on for every active organisation.

### Leads (`--tenant-id`)

| Command                                                                                                                | What it does                                                                                        | Service                 |
| ---------------------------------------------------------------------------------------------------------------------- | --------------------------------------------------------------------------------------------------- | ----------------------- |
| `leads list [--search S] [--where-*] [--names]`                                                                        | a page (50) of the team's leads, with the total                                                     | `LeadDesk.leads`        |
| `leads add --name N [--phone --email --company --city --note] [--owner-person-id P] [--side live/cold] [--pipeline K]` | one lead; to P, or by the lead rules                                                                | `LeadDesk.add`          |
| `leads assign (--lead-id L ... / --where-*) (--to-person-id P / --rules)`                                              | give leads to a person or by the rules                                                              | bulk job `assign`       |
| `leads reassign --person-id FROM --to-person-id TO [--where-*]`                                                        | every lead FROM owns (not the Bin), or those matching                                               | bulk job `assign`       |
| `leads stage (--lead-id / --where-*) --step K [--outcome-reason R] [--reason-note N] [--next-action-at ISO]`           | move to one of the business's stages; a lead the move doesn't suit is skipped with the app's reason | bulk job `stage`        |
| `leads archive` / `restore-archive` / `bin` / `restore-bin`                                                            | Archive and the Bin (owners and admins)                                                             | bulk job, `shelf.move`  |
| `leads import --input FILE.json`                                                                                       | `import-leads-file.py`'s input; its tenant and issue must match                                     | `import-leads-file.run` |

Selections: `--lead-id` (repeatable) or the Leads list's own filter: `--where-owner`, `--where-unassigned`,
`--where-step`, `--where-stage`, `--where-side inbound/cold`, `--where-search`, `--where-source`, `--where-pipeline`,
`--where-shelf archived/bin`. A filter is frozen by the bulk job (up to 2,000 leads); `--expected-total N` refuses
when the count changed since you looked. Every bulk change can be undone in the app for 30 minutes (its job id is in
the receipt).

## API and MCP parity

The same primitives for an organisation's API key (`/v1/api`) and its MCP tools (`/v1/mcp`), in
`packages/python/ac_platform/integrations/admin_api.py`. Every change needs an organisation's key held by an owner or
admin (a connected app or a seller's key is refused), takes a `request_id` (the same one again changes nothing) and
goes through the same app service as the CLI, with the app's own rules (seats: a full workspace refuses an invite with
`seats_full`; only the owner changes roles).

| Primitive                                      | API (`/v1/api`)                                 | MCP tool                                    | Scope                 |
| ---------------------------------------------- | ----------------------------------------------- | ------------------------------------------- | --------------------- |
| people list                                    | `GET /team`                                     | `list_team`                                 | `team:read`           |
| workspace show                                 | `GET /workspace`                                | `get_workspace`                             | `team:read`           |
| pending invites                                | `GET /team/invites`                             | `list_invites`                              | `team:read`           |
| invite                                         | `POST /team/invites`                            | `invite_member`                             | `team:manage` (new)   |
| resend invite                                  | `POST /team/invites/{id}/resend`                | `resend_invite`                             | `team:manage`         |
| cancel invite                                  | `POST /team/invites/{id}/revoke`                | `revoke_invite`                             | `team:manage`         |
| set role (the owner's key only, as in the app) | `POST /team/{person_id}/role`                   | `set_member_role`                           | `team:manage`         |
| remove member                                  | `POST /team/{person_id}/remove`                 | `remove_member`                             | `team:manage`         |
| leads list/find                                | `GET /leads?stage=&search=`                     | `list_leads`, `search`                      | `leads:read`          |
| lead add                                       | `POST /leads`                                   | `add_lead`                                  | `leads:write`         |
| import                                         | `POST /leads/imports`, `/leads/imports/uploads` | `import_leads`, `create_lead_import_upload` | `leads:write`         |
| assign                                         | `POST /leads/{id}/assign`, `POST /leads/bulk`   | `assign_lead`, `update_leads`               | `leads:assign`        |
| reassign by person                             | `POST /leads/reassign`                          | `reassign_leads`                            | `leads:assign`        |
| stage                                          | `POST /leads/{id}/stage`, `POST /leads/bulk`    | `move_stage`, `update_leads`                | `leads:stage`         |
| archive / bin / restore                        | `POST /leads/shelf`                             | `shelve_leads`                              | `leads:archive` (new) |

Lead changes over 5 leads are previewed first (`preview: true` returns the counts and a `preview_sha`; send it back to
apply), the owner's pause in Organisation → AI apps stops them, and each is a Leads bulk job that can be undone in the
app for 30 minutes.

**CLI only, by design** (an operator with the owner's approval): transfer ownership, rename a person's account, rename
the workspace, its verified e-mail domains (the app proves those by DNS), the AI-apps switch itself (a key never widens
what keys may do), making or listing workspaces (a key belongs to one) and the Bin's purge.

**Scope grants.** Saved tier settings beat the code's defaults, so `team:manage` and `leads:archive` reach no tier until
granted per environment with `scripts/data-changes/developer-platform-override.py --grant-scope tier=scope` (dev:
organisation, enterprise and unbilled, as for `leads:assign`). Production grants are the orchestrator's, after the
release that carries these routes, with a snapshot first.

## Examples (dev)

```sh
admin.py leads archive --tenant-id T --lead-id L --actor-person-id P --approver owner-chat --issue AUT-1 \
  --environment development               # dry run: status eligible, rolled_back
admin.py leads archive ... --apply         # status applied, audit written
admin.py leads archive ... --apply         # status replayed
admin.py leads reassign --tenant-id T --person-id SELLER_A --to-person-id SELLER_B --where-step new ...
admin.py workspaces switches --tenant-id T --environment development   # shows the switch
```

## Tests

- `tests/unit/organisations/test_admin_cli.py`: arguments, groups and old names, reads without approval, selections,
  derived command ids, masked output.
- `tests/database/test_admin_cli_data_change_postgresql.py`: every command on PostgreSQL: dry run leaves nothing and
  audits nothing, apply audits once, a rerun replays.
- `tests/database/test_integrations_admin_api_postgresql.py` and `tests/unit/integrations/test_platform_apps.py`: the
  API routes and MCP tools.
- Dev proof 17 Nov 2026 in "API Import Proof (Fictional)": leads add, archive, restore-archive, bin, restore-bin
  (dry, apply, rerun), the AI-apps switch on and off, rename unchanged, a refused stage move with the app's reason.
- Dev API proof 17 Nov 2026 in AC Sales Sandbox, with a key of `team:read`, `leads:read`, `leads:archive` and
  `leads:assign` (revoked after): the workspace and invites read, one lead archived and restored (a retry returned the
  same job), a preview of archiving 1,989 leads changed nothing, an invite without `team:manage` refused, MCP listing
  the new tools. Dev tiers granted `team:manage` and `leads:archive` (organisation, enterprise, unbilled; settings
  revision 8).
