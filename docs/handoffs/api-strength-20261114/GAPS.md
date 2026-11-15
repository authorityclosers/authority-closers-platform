# Sales X-Ray API, MCP and CLI: the gap list (14 Nov 2026)

The owner (14 Nov 2026, via the Orchestrator): "the API has to be made ten times stronger, MCP, CLI… connecting with
Claude, pushing thousands of leads using Claude, uploading leads from Claude to Sales X-Ray, managing… API and backend
strongness is important. Admin-level strongness."

Audited on dev/live at b9e18462. The API is `/v1/api` (`packages/python/ac_platform/integrations/api_http.py`), the
remote MCP is `/v1/mcp` (`integrations/mcp_http.py`), and the CLI with stdio MCP is
`apps/sales-xray-web/public/developers/sx.py`. Keys are `sxk_live_`/`sxk_test_`; OAuth gives `sxa_` tokens.

## What exists today

| Job | API | MCP | CLI |
|---|---|---|---|
| Add one lead (idempotent by `external_id`) | `POST /leads` | `add_lead` | `add-lead` |
| List and read leads, duplicates | `GET /leads`, `/leads/{id}`, `/duplicates` | yes | `leads`, `lead` |
| Notes, tasks, field edits, undo | `POST /leads/{id}/notes`, `/tasks`, `PATCH /leads/{id}` (owner switch), `/changes`, undo | notes, tasks, undo (no `update_lead`) | `note`, `task`, `changes`, `undo` |
| Calls and their facts | `GET /calls`, `/calls/{id}`, `/calls/{id}/facts` | `list_calls`, `get_call`, `call_facts`, `search`, `fetch` | `calls`, `facts` |
| Upload a recording | `POST /calls`: app-only `calls:write` (OAuth, never a key), Pulse-gated, 100 MB in one request, held in an inbox until a person adds it | no | no |
| Keys | created and revoked only on the signed-in Settings page; SHA-256 stored; 25 per workspace; `last_used_at` | | |
| Admin | `GET /v1/admin/integrations`: keys, webhooks and connections per organisation; revoke and disable | | |

## Gaps, in the order they will be built

1. **Bulk lead import (P0, owner's first ask).** There is no batch endpoint, no async job, no progress and no per-row
   report through the API, MCP or CLI. The signed-in file import is synchronous, one transaction, at most 2,000 rows.
   - Build a job API:
     - `POST /v1/api/leads/imports` takes JSON rows with an `Idempotency-Key`; it runs async;
     - `GET /v1/api/leads/imports/{id}` gives progress;
     - `GET …/rows` gives the per-row outcomes (created, repeat, known, failed with a code).
   - It dedupes through the same `LeadDesk.ingest` as every intake (external id, then phone, then email).
   - Add a narrow `leads:import` scope, an MCP `import_leads` and `get_lead_import`, and a CLI `import-leads` (CSV or
     JSON, chunked, waits, writes failures to a file).
   - Proof: 5,000 fictional leads into a dev test workspace.
2. **Recording upload by API (P0).**
   - Keys can't upload (`calls:write` is app-only). Uploads don't go to analysis by themselves. There is no resumable
     or chunked upload, no presigned URL and no upload webhooks.
   - Build a key-scoped upload that goes straight into analysis under the workspace's standing consent:
     - status polling;
     - an MCP tool that takes a URL-free upload handle;
     - a CLI `upload`.
3. **Admin for operators.**
   - Admin has no view of import jobs or their failures, app uploads, per-key usage or rate-limit hits, and no
     "AI writes" tab.
   - Build: import jobs and failed rows per organisation, plus per-key request counts and 429s.
4. **Stage, assign and owner by API.**
   - Today these exist only in the signed-in app (`/v1/lead-desk/leads/{id}/stage`, `/assign`, `/leads/bulk`).
   - `PATCH /v1/api/leads/{id}` can't change them, and MCP has no `update_lead`.
5. **Reports and coaching by API.**
   - Only facts are public. Report body, summary, scores, coaching, transcript and the Word file are session-only.
   - `coaching:read` is "not yet". `/calls` has no date, seller or lead filters.
6. **Workspace and members by API.** Only `GET /me` exists; members, invites and roles are session-only.
7. **Keys.**
   - No rotation, rename or scope edit; no per-key request counts.
   - `monthly_requests` is recorded but not enforced.
   - `webhooks:manage` is checked by no route, and the tier's webhook count is not enforced.
   - One webhook per organisation.
8. **Limits and errors.**
   - Rate limits are in-memory per process, with no `X-RateLimit-*` headers.
   - Errors come in three shapes: `{"error":{code,message}}`, FastAPI's `{"detail":[…]}` and problem+json for a 413.
   - The documented code list misses several codes.
   - `GET /leads` has no `search`.
9. **Docs drift.**
   - `docs/architecture/INTEGRATIONS.md` says the MCP has 7 tools and refuses foreign Origins.
   - `apps/sales-xray-web/app/developers/reference.ts` lacks PATCH and the newer codes.

## Guardrails kept

- Writes go through the same Lead Desk commands as the app.
- Every write carries provenance (the key or app).
- AGENTS.md: history is superseded, never overwritten.
- Imports never become canonical state by side effect.
- No real customer data in any proof: dev test workspaces with fictional leads only.

## Status (15 Nov 2026)

- **Built (landing as migration 0154):** gap 1, bulk lead import.
  - `POST /v1/api/leads/imports` (`leads:write`, `Idempotency-Key`, up to 10,000 rows, 4 MB) and
    `GET …/imports`, `…/imports/{id}`, `…/imports/{id}/rows`, in `integrations/lead_imports.py`.
  - The rows are filed 250 at a time by an in-API runner through `Intake.commit` (with `start_row`, `refs` and a
    per-row `report`). One Undo import covers the whole job; a revoked key stops what waits.
  - MCP `import_leads` (250 a call) and `get_lead_import`; CLI `sx import-leads` and `sx import`.
  - Admin: `GET /v1/admin/integrations/imports`, `…/imports/{id}/problems`, `POST …/imports/{id}/stop` (audited).
  - Migration 0154 adds two tables.
- **Needs a decision before building gap 2 (recording upload by key):**
  1. Whose call is it: the key maker's, or a seller the request names (an `X-Owner` email)?
  2. Consent: the per-upload `X-Recording-Consent: participants-informed`, plus the workspace's standing analysis
     consent (AGENTS.md: no external processing before the consent and retention gates)?
  3. Whose analysis minutes it uses.
  4. Resumable chunked sessions now, or one idempotent request (`X-Source-SHA256`) first?
