# Admin from the command line and from AI assistants (ac-admin)

`ac-admin.py` lets a person or an AI assistant work with Admin using a staff key. It is one Python file, needs Python 3.10 or later, and uses only the standard library.

Download it from Admin at **Integrations → Staff keys**. It is served from `/tools/ac-admin.py`.

## Get a key

1. Sign in to Admin. A key can only be made within 10 minutes of signing in, and only from a verified AC control account.
2. Go to **Integrations → Staff keys → Make a staff key**.
3. Choose what the key may do:

   | Scope            | What it allows                                                                   | How to get it                      |
   | ---------------- | -------------------------------------------------------------------------------- | ---------------------------------- |
   | `settings:read`  | Read every setting Admin lists                                                   | Always included                    |
   | `settings:write` | Change those settings through each area's own route, with its checks and audit   | Tick **May change settings**       |
   | `admin:read`     | Content-free reads of calls, organisations, the review queue and analysis health | Tick **May read calls and health** |

4. Copy the key. It is shown once; only its SHA-256 is kept.
5. A key lasts 30 days. Each person may hold at most two active keys. Revoke a key at once on the same page.

## Use it

```bash
export AC_ADMIN_KEY=ac_live_...
```

- Set `AC_ADMIN_BASE` to the Admin address of staging or dev; the default is production.
- The key is never passed as an argument and the tool never prints it. A command that carries a key-shaped argument is refused.

| Command                                                       | What it returns                                                                                                                                                           |
| ------------------------------------------------------------- | ------------------------------------------------------------------------------------------------------------------------------------------------------------------------- |
| `ac-admin settings list`                                      | Every setting, its value now, and whether it can be changed here                                                                                                          |
| `ac-admin settings get ID`                                    | One setting: value, revision, options or bounds                                                                                                                           |
| `ac-admin settings set ID VALUE [--reason TEXT]`              | Changes the setting through its area's own route                                                                                                                          |
| `ac-admin orgs`                                               | Organisations and workspaces, each with its kind                                                                                                                          |
| `ac-admin calls [--organisation ID] [--status S] [--limit N]` | The newest calls: ids, organisation, salesperson, status, language, length, provider and model                                                                            |
| `ac-admin call-map CALL_ID`                                   | One call's stages, from C1 audio check to C6 published, plus the fast and deep reads and review. For each stage: status, start and finish, time, cost, provider and model |
| `ac-admin review-queue [--pipeline KEY] [--limit N]`          | The calls a review pipeline samples, with progress                                                                                                                        |
| `ac-admin health [--days N]`                                  | Jobs finished, failed and stuck, timings, and cost per minute                                                                                                             |

Output is JSON. Exit codes:

- `0`: done.
- `1`: Admin refused; its answer is printed.
- `2`: a usage or connection problem.

## As an MCP server

Run `ac-admin mcp` to serve tools on stdio. Every command above is offered as a tool:

- `list_settings`, `get_setting`, `set_setting`
- `list_organisations`, `list_calls`, `get_call_map`, `get_review_queue`, `get_health`

Example entry in an assistant's MCP configuration:

```json
{
  "mcpServers": {
    "ac-admin": {
      "command": "python3",
      "args": ["/path/to/ac-admin.py", "mcp"],
      "env": { "AC_ADMIN_KEY": "ac_live_..." }
    }
  }
}
```

## What a key can never do

- **No call content.** A key never reads transcripts, quotes, facts' values, evidence or report text. These stay in the browser, behind their own audited reads.
- **Browser-only areas.** Billing, payment, plan prices, credit balances, secrets, passwords and staff keys themselves stay in the browser.
- **Write audit.** Every change made with a key is audited twice: by its area, and as `admin.staff_key_used` with the key's prefix.
- **Rate limit.** A key may make at most 60 requests a minute.

Code:

- `packages/python/ac_platform/admin_settings/staff_keys.py`: scopes, `READS` and `route_scope`.
- `apps/admin-web/public/tools/ac-admin.py`: the tool itself.
- Tests: `tests/unit/http/test_ac_admin_cli.py` and `tests/unit/http/test_staff_key_reads.py`.
