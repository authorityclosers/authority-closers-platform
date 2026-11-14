# API, MCP and CLI gaps against the app (15 Nov 2026)

Read-only audit for the orchestrator. The owner wants the API, MCP and CLI "ten times stronger": "pushing thousands of
leads using Claude", recording upload by API, and "Admin-level strongness". This file lists what a Claude or MCP
client, an API key and the `sx` CLI can do today, against what an owner or admin does in the app, and ranks the gaps.
Nothing here was built.

Source: the dev/live workbench at 23f886ea6. Files read:

- `packages/python/ac_platform/integrations/`: `api_http.py`, `mcp_http.py`, `scopes.py`, `tier_policy.py`,
  `lead_imports.py`, `app_uploads.py`, `webhooks.py`, `oauth_http.py`, `write_policy.py`;
- `apps/sales-xray-web/public/developers/sx.py`;
- all 799 FastAPI routes, dumped by a script over `ac_platform`.

## What works today

**Key API (`/v1/api`, 20 routes):**

- `/me`.
- Calls: list, get, and facts (`reports:read`).
- Leads: list, get, add, and update (name, company, city, interest and language only).
- Bulk import: up to 10,000 rows per import and 50,000 a day. It sets stage, owner and source; it dedupes, runs the
  lead rules and can be undone for 48 hours.
- Duplicates: list and get.
- Notes and tasks: add.
- Changes: list and undo.
- `POST /calls`: a recording upload, but only from an app a person connected (more under gap 2).

**MCP (`/v1/mcp`, 15 tools):** `whoami`, `search`, `fetch`, `list_calls`, `get_call`, `call_facts`, `list_leads`,
`get_lead`, `list_duplicates`, `get_duplicate`, `add_lead`, `import_leads` (rows inline), `get_lead_import`,
`add_note`, `add_task`, `list_my_changes`, `undo_change`.

**`sx` CLI (13 commands):** `me`, `calls`, `facts`, `leads`, `lead`, `add-lead`, `note`, `task`, `import-leads`,
`import`, `changes`, `undo`, `mcp`.

- `import-leads` reads a CSV or JSON file of any size and sends it 5,000 rows at a time.
- `--wait` and `--failures` give a full bulk path from a laptop.

**Scopes:**

- Keys can hold `calls:read`, `reports:read`, `leads:read`, `leads:write`, `leads:notes`, `leads:tasks`,
  `leads:update` and `webhooks:manage`.
- `calls:write` is app-only.

**Tiers** (`tier_policy.py` defaults; Admin can change them):

| Tier         | Scopes                           | API keys | Rate limits                                        | Webhooks | Requests a month |
| ------------ | -------------------------------- | -------- | -------------------------------------------------- | -------- | ---------------- |
| Trial        | read only                        | no       |                                                    |          | 2,000            |
| Personal     | calls and reports only, no leads | no       |                                                    |          |                  |
| Organisation | every scope                      | yes      | 120 a minute per key, 600 a minute per workspace   | 1        | 100,000          |
| Enterprise   | every scope                      | yes      | 300 a minute per key, 2,000 a minute per workspace | 5        |                  |

**Webhook events:** `lead.created`, `lead.stage_changed`, `lead.closed` and `lead.handover`.

## The gaps, ranked by owner value

Sizes: S is up to a day, M is two to four days, L is one to two weeks. Tier is the lowest plan that should get it.

| #   | Gap                                                        | Missing route, tool or command                                                                                                                             | Scope                                       | Tier         | Size                |
| --- | ---------------------------------------------------------- | ---------------------------------------------------------------------------------------------------------------------------------------------------------- | ------------------------------------------- | ------------ | ------------------- |
| 1   | A Claude connector can't write                             | Connect defaults to read; `advertise_writes` off                                                                                                           | `leads:write`, `leads:notes`, `leads:tasks` | Organisation | S                   |
| 2   | No recording upload for a workspace key                    | `POST /v1/api/recordings` (+ status), MCP `create_recording_upload`, `sx upload`                                                                           | `calls:write` for keys                      | Organisation | L                   |
| 3   | No stage, owner or bulk change on existing leads           | `POST /v1/api/leads/{id}/stage`, `/assign`, `POST /v1/api/leads/bulk`; MCP `move_stage`, `assign_lead`, `update_leads`; `sx stage`, `sx assign`, `sx bulk` | new `leads:stage`, `leads:assign`           | Organisation | M                   |
| 4   | Claude can't push thousands of leads economically          | MCP `import_leads_from_file` (signed CSV upload or Sheet link); MCP `update_lead` (the API has it)                                                         | `leads:write`, `leads:update`               | Organisation | M                   |
| 5   | No call report by API                                      | `GET /v1/api/calls/{id}/report` (+ `.docx`), saved reports list; MCP `get_report`, `list_reports`; `sx report`                                             | `reports:read`                              | Personal     | M                   |
| 6   | No call or report webhooks; `webhooks:manage` has no route | events `call.received`, `call.analysed`, `report.ready`; `GET/PUT /v1/api/webhook`, `sx webhook`                                                           | `webhooks:manage`                           | Organisation | M                   |
| 7   | Team and roles invisible to apps                           | `GET /v1/api/team` (names, roles, active, lead capacity); MCP `list_team`; later invite and role change                                                    | `team:read`; `team:manage`                  | Organisation | S (read), M (write) |
| 8   | Tasks can only be added                                    | `GET /v1/api/tasks`, `POST /v1/api/tasks/{id}/done`, `/snooze`; MCP `list_tasks`, `complete_task`; `sx tasks`, `sx done`                                   | `leads:tasks`                               | Organisation | S                   |
| 9   | Analysis time unreadable by apps                           | `GET /v1/api/analysis-time` (+ `/team` for owners); MCP `analysis_time`; `sx minutes`                                                                      | `calls:read`                                | Personal     | S                   |
| 10  | No Admin operator path for Claude                          | staff-only ops MCP and `sx ops`: minute grants, tier and plan overrides, seat grants, org members and owner, key revoke, import stop                       | staff OAuth, per-action                     | Staff only   | L                   |
| 11  | Coaching not reachable by apps                             | MCP `call_coaching`, `team_coaching`; `GET /v1/api/coaching`                                                                                               | `reports:read`                              | Organisation | M (ask-dipak)       |
| 12  | Duplicates readable, not mergeable; no lead delete         | `POST /v1/api/duplicates/{id}/merge`; delete stays app-only                                                                                                | `leads:write`                               | Organisation | M                   |

### 1. A Claude connector can't write (S, do first)

**Today:**

- `oauth_http.DEFAULT_SCOPES` is `calls:read reports:read leads:read`.
- `tier_policy.DEFAULTS["advertise_writes"]` is False, so `mcp_http.tools_for` lists only the tools the granted
  scopes allow.
- A Claude.ai connector made with Connect sees no `add_lead`, `import_leads`, `add_note` or `add_task`, and isn't
  told it could ask for them.
- So "pushing leads using Claude" fails at the first step for the owner's own Claude. API keys and the CLI aren't
  affected.

**Fix:**

- Turn `advertise_writes` on in Admin → economics, after checking the production value through the logged read path.
- Let Connect's consent screen offer the write scopes the tier allows.

### 2. Recording upload by API (L)

**Today:**

- `POST /v1/api/calls` takes a recording only from an app a person connected (`reach == "person"`), and only when
  Pulse is configured on that server (`pulse_on`).
- The file lands in that person's inbox (`/v1/sales-xray/app-uploads`), where they import it by hand. It isn't
  analysed by itself.
- `calls:write` can't be put on an API key at all (it's an `APP_SCOPES` scope).

**Missing:**

- `POST /v1/api/recordings`: a resumable upload or a signed-URL `PUT`, with `seller` (a teammate), `lead_id`,
  `called_at` and `direction`.
- The upload goes straight into analysis under the workspace's analysis time. The status reads queued, analysing,
  done or failed.
- MCP `create_recording_upload` returns an upload URL, because a tool call can't carry audio.
- `sx upload FILE --lead ID --seller NAME [--wait]`.

**Gates (AGENTS.md: no external processing before consent, retention, provenance and provider gates):**

- The key's workspace must have accepted the recording terms, as an in-app upload does.
- Each upload carries the uploader's attestation, and the provider path is the one already approved for in-app
  uploads.
- No minutes or prices in any answer; time left only.

### 3. Stage, owner and bulk changes on existing leads (M)

**Today:**

- `PATCH /v1/api/leads/{id}` changes only `write_policy.UPDATE_FIELDS` (name, company, city, interest, language).
- The app moves stage (`/v1/lead-desk/leads/{id}/stage`), assigns (`/assign`) and acts in bulk (`/leads/bulk`,
  `/leads/distribute`).
- None of that is in the key API, MCP or CLI. An import can set stage and owner only for new or matched rows.

**Missing:**

- `POST /v1/api/leads/{id}/stage` (stage key or name, with lost reason), and `POST /v1/api/leads/{id}/assign`.
- `POST /v1/api/leads/bulk`: up to 1,000 ids, or a saved filter, with one change (stage, owner, tag), a preview, a
  request_id, and undo through `/changes`.
- MCP `move_stage`, `assign_lead`, `update_leads`; CLI `sx stage`, `sx assign`, `sx bulk --from FILE`.
- Each change gets its own scope, as `docs/product/ai-writes.md` does for notes and tasks.

### 4. Thousands of leads through Claude (M)

**Today:**

- MCP `import_leads` takes the rows inline. 10,000 rows in one tool call is far beyond a Claude message, so Claude
  pushes a few hundred at a time and spends the conversation doing it.
- MCP has no `update_lead` although the API has it.

**Missing:**

- MCP `import_leads_from_file`: a signed upload URL for a CSV, or a Google Sheet link (the app already reads Sheets:
  `/v1/lead-desk/imports/google-sheet`). It then reports through `get_lead_import`.
- MCP `update_lead`.

### 5. Call reports by API (M)

**Today:**

- `reports:read` covers only `call_facts`.
- The report itself (summary, scores, coaching points, next steps, transcript, `.docx`) and Reports V4's saved
  reports are app-only (`/v1/conversation/acquisition/submissions/...`, `PUT .../saved`).

**Missing:** a public report contract with `GET /v1/api/calls/{id}/report` (+ `.docx`, transcript),
`GET /v1/api/reports?saved=true`, MCP `get_report` and `list_reports`, and `sx report ID [--docx]`. Reports V4 owns
the saved-reports server.

### 6. Call and report webhooks, and webhook management by key (M)

**Today:**

- Only the lead events above.
- `webhooks:manage` is a key scope with no route behind it; the app manages the one webhook
  (`/v1/sales-xray/integrations/webhook`).

**Missing:** events `call.received`, `call.analysed` and `report.ready`, which pair with gap 2; `GET/PUT
/v1/api/webhook`, `.../test` and `.../deliveries`; `sx webhook set|test|deliveries`.

### 7. Team and roles (S read, M write)

**Today:** imports take an owner's email or name, but no app can list the team, so Claude guesses names. The app has
`/v1/organisation/members` (+ invites, role change, remove) and `/v1/lead-desk/team` (capacity, languages).

**Missing:**

- Read: `GET /v1/api/team` and MCP `list_team` (names, never emails, in owner views; roles, active, capacity).
- Write, admin-only: `team:manage` for invite, role and remove.

### 8. Tasks (S)

**Today:** apps can add tasks but not list, complete or snooze them. The app has `GET /v1/lead-desk/tasks`,
`PATCH /tasks/{id}`, `/snooze` and `/{action}`.

**Missing:** the same through `/v1/api/tasks`, MCP `list_tasks` and `complete_task`, and `sx tasks` / `sx done`.

### 9. Analysis time (S)

**Today:** the app reads `/v1/me/analysis-time` and owners read `/team`.

**Missing:** `GET /v1/api/analysis-time` (+ `/team`), MCP `analysis_time` and `sx minutes`. Time only, never a price.
It's needed before a bulk recording upload (gap 2).

### 10. Admin operator path (L, staff only)

**Today:** every operator action is a staff-session route behind the Admin web:

- minute grants: `/v1/admin/conversation-minute-accounts/.../grants`;
- seat grants, members and owner transfer: `/v1/platform/organisations/{tenant}/...`;
- credit grants: `/v1/platform/billing/.../credit-grants`;
- tier overrides and economics: `/v1/admin/economics`;
- plan prices: `/v1/admin/plan-prices`;
- key and webhook revoke, import stop: `/v1/admin/integrations/...`;
- also server-side CLIs such as `scripts/ops/grant-minutes`.

None of it is reachable by a key or MCP.

**Missing:** a staff-only ops MCP and `sx ops` with staff OAuth. Every write follows AGENTS.md OWNER-APPROVED DATA
CHANGES:

- dry-run by default, printing before and after;
- the owner's approval text and the issue are required;
- one transaction and an audit event;
- production takes a snapshot first.

Billing, payments, plan prices, secrets and deletions stay out (AGENTS.md: never through this path).

### 11. Coaching (M, ask-dipak's area)

**Today:** `/v1/me/coaching` (+ team, people, calls) is app-only.

**Missing:** MCP `call_coaching` and `team_coaching`, behind `reports:read`. No official AI scoring before the
AC-SVAL gates.

### 12. Duplicates and deletion (M)

**Today:** apps can read duplicate pairs but can't merge them.

**Missing:** `POST /v1/api/duplicates/{id}/merge`. Lead deletion stays in the app (OWNER-APPROVED DELETIONS).

## Notes for whoever builds these

- Rate limits are fine for bulk once gaps 3 and 4 exist. Without them, 10,000 single updates at the organisation
  tier's 600 a minute per workspace take about 17 minutes and use 10% of the monthly 100,000 requests.
- Every new write follows the existing AI-writes pattern: `request_id`, `preview`, an entry in `/changes` with undo,
  and one scope per kind of change.
- Owner views show names, never emails. No prices anywhere outside Admin.
