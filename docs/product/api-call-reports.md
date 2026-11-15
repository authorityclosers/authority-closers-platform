# Call reports by API, MCP and CLI

Gap 5 of `docs/product/api-mcp-cli-gaps-20261115.md`, built on 15 Nov 2026 at the
orchestrator's request.

Apps can read the same report a person reads in Sales X-Ray:

- the report itself;
- its Word file;
- its transcript;
- the list of reports, Saved reports included.

All of it needs `reports:read`, which every plan that reads calls already includes. There is no
new scope. The code is in `packages/python/ac_platform/integrations/reports_api.py`.

## Who reads which report

The app's own rule applies (`GuestOwnership.organisation_call_reader`):

| Caller                             | Opens the reports of                  |
| ---------------------------------- | ------------------------------------- |
| A person (connected app), any role | their own calls                       |
| A person who is an owner or admin  | also every call in their organisation |
| An organisation API key            | every call in its organisation        |

Managers and viewers see the team's calls in `GET /calls`, but open only their own reports,
as in the app. The role is read fresh on every request, so a demoted owner is back to their
own reports at once.

**Saved** means the app's Saved reports (Reports V4) of the person the key acts as. For a
connected app that is the person; for an organisation key it is the person who made the key.

## Routes (`/v1/api`)

| Route                               | Answer                                                                                                                                           |
| ----------------------------------- | ------------------------------------------------------------------------------------------------------------------------------------------------ |
| `GET /reports?saved=true&before=ID` | Calls with a ready report, newest first, 50 a page: `id`, `title`, `created_at`, `duration_seconds`, `open_url`, `saved`, then `next_before`     |
| `GET /calls/{id}/report`            | `schema` `sales-xray.api-report/1`, `call`, `review_status`, `official_score: false`, `transcript_revision`, `report` (the app's report content) |
| `GET /calls/{id}/report.docx`       | The same report as a Word file (the app's export)                                                                                                |
| `GET /calls/{id}/transcript`        | `call`, `revision`, `duration_ms`, `segments`                                                                                                    |

Refusals:

| Code                     | When                                         |
| ------------------------ | -------------------------------------------- |
| 403 `scope_missing`      | The key lacks `reports:read`                 |
| 404 `call_missing`       | Not a call this caller may open              |
| 404 `report_not_ready`   | The report is still being made               |
| 409 `report_unavailable` | The stored report can't be shown or exported |

## MCP and CLI

The MCP tools (`/v1/mcp`, and `sx mcp` on stdio) are:

- `list_reports` (`saved`, `before`);
- `get_report` (`call_id`);
- `get_transcript` (`call_id`).

The Word file is API and CLI only, because a tool answer carries text.

The CLI commands are:

```bash
sx reports [--saved] [--before CALL_ID]
sx report CALL_ID                    # the report as JSON
sx report CALL_ID --transcript       # its transcript
sx report CALL_ID --docx call.docx   # its Word file
```

## How it reads

A key has no browser session. The app's report read re-admits the signed-in session, so it
can't serve a key. Instead each report is read in these steps:

1. The call is found through the same library query `GET /calls` uses. Deleted, revoked and
   expired calls aren't in it.
2. Its recording is locked for share, as the app's read locks it, so erasure and revocation
   wait.
3. The app's post-authorization projection (`AcquisitionReports.render_report` and
   `render_transcript`) shows it.

The result is the same content the app shows, with sensitive parts withheld. The previous call's
context is never included, and internal ids (recording, run, source hash) are left out.

This is an AI report and never an official score. AC-SVAL gates any official scoring, and
nothing here adds one.

## Tests

- `tests/database/test_integrations_reports_postgresql.py`:
  - an organisation key reads the list, Saved reports, a report, its Word file and its
    transcript;
  - it is refused without the scope, and for a call that isn't ready or isn't there;
  - a person's reach follows their role.
- `tests/unit/integrations/test_reports_api.py`: the scope on each tool, the owner and admin
  rule, tool arguments, and the `sx` commands.
