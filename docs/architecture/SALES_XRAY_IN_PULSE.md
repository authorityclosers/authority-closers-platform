# Sales X-Ray inside Pulse

The owner asked on 20 Oct 2026 for Sales X-Ray to appear in Pulse as an installed app and MCP server. People sign in to it inside Pulse with the Sales X-Ray (Authority Closers) account they bought or were added to.

Both companies belong to the same owner, so sharing code between them is allowed. Each company still keeps its own data and its own secrets.

This page is the design for both sides. The Pulse repository has a short page that points here: `docs/architecture/SALES_XRAY_APP.md`.

## In one picture

```
Pulse (EA server)                                     Sales X-Ray (AC server)
-----------------                                     -----------------------
Apps → Sales X-Ray → Connect ──browser──▶ /connect   consent: "Connect Pulse to your
                                                      Sales X-Ray account?" (Allow)
/apps/sales-xray/callback ◀──browser── code + state
  POST code → Pulse API ──server──▶ POST /v1/oauth/token (PKCE, client secret)
  tokens sealed in pulse_priv.sales_xray_link
Calls / Leads tabs  ── Pulse API ──server──▶ GET /v1/api/calls, /leads …  (Bearer sxa_)
Ask (Pulse's assistant, codex) ── MCP ──server──▶ POST /v1/mcp (Bearer sxa_, from its env)
```

## 1. How a Pulse user links their Sales X-Ray account

1. **Pulse registers itself.** The first time anyone in a company presses Connect, Pulse calls `POST /v1/oauth/register` (RFC 7591).
   - It sends the name "Pulse", the company's exact return address (`https://<company host>/apps/sales-xray/callback`) and `client_secret_basic`.
   - Sales X-Ray answers with a `sxc_` client id and an `sxcs_` secret.
   - Pulse seals the secret with its own document keyring and keeps it per company and Sales X-Ray address in `pulse_priv.sales_xray_client`.
   - Nobody sets a secret by hand, in Infisical or anywhere else.
2. **Pulse shows as checked.** Sales X-Ray marks the app as made by Estate Autopilots only when its name is "Pulse" and every return address is on Pulse's own host for that environment (`first_party.py`):
   - `pulse.estateautopilots.com` on production;
   - `pulse-staging.estateautopilots.com` on staging;
   - `pulse-dev.estateautopilots.com` on dev.

   A copy of Pulse on any other host is shown as an unchecked app, with its return address.
3. **Connect.** Pulse makes a PKCE verifier and a random state, and keeps them for 10 minutes, bound to the person (`pulse_priv.sales_xray_attempt`). It then sends the browser to Sales X-Ray's `/connect`.
4. **Consent.** The person signs in to Sales X-Ray (any sign-in method) in the workspace they want: Personal, or an organisation they belong to. They see:
   - "Connect Pulse to your Sales X-Ray account?";
   - "Made by Estate Autopilots";
   - the workspace and their role;
   - the permissions asked for.

   Allow sends them back with a one-time code. Any active member may approve, because the app will act as that person only.
5. **Back in Pulse.** The callback page posts the code and state to the Pulse API.
   - The API takes the attempt, which works once, for the same person only.
   - It swaps the code at `/v1/oauth/token` with the verifier and its client secret.
   - It seals the tokens in `pulse_priv.sales_xray_link`, one row per person.
   - The code never leaves the person's browser and Pulse's server, and the page drops it from the address bar.
6. **Disconnect.** Pulse revokes the refresh token (`/v1/oauth/revoke`, which ends the connection at Sales X-Ray) and deletes its row. In Sales X-Ray, the person can remove the connection with `/v1/me/connected-apps`. An organisation owner or admin sees every connection in Integrations and can remove it there.

## 2. What Sales X-Ray guarantees for a person's connection

This is a "platform app" connection: the app has no `tenant_id` of its own.

- **What it reads.** The token acts as the person and reads what that person sees in Sales X-Ray, checked live on every request:
  - a member reads their own calls and their own leads;
  - an owner or admin reads their team's;
  - in a Personal workspace, the person reads their own calls, and leads answer `organisation_only`.
- **Leaving.** A person who leaves the organisation (membership no longer active) gets `403 access_ended` at once. The connection is not deleted; it stops working.
- **A replayed code** ends only that person's connection, not their colleagues'.
- **Tokens.** Access tokens last 1 hour. Refresh tokens last 30 days and are replaced on use; reusing an old refresh token ends the connection. Pulse refreshes under a row lock, so two pages loading at once never reuse one.
- **Withheld parts** of calls are never quoted, by the API or the MCP server.

## 3. What appears inside Pulse

- **Apps** (`/apps`) lists installable apps, above Pulse's own device install guides. Sales X-Ray is the first, and the list is repo data. The company's admin turns the app on with its module switch, `sales_xray`, which on dev is server-switched by `PULSE_SALES_XRAY=1`. Each person then connects their own account.
- **Sales X-Ray app page** (`/apps/sales-xray`):
  - **Not connected:** what it does, and a Connect button.
  - **Connected:** the Sales X-Ray account and workspace, and Disconnect. It has three tabs:
    - **Calls:** title, date, length, whether the report is ready; open a call to see the facts found in it (the report highlights); "Open in Sales X-Ray" for the full report.
    - **Leads:** stage filter, name, stage, source, next step; open one for its details.
    - **Ask:** ask Pulse's assistant about your Sales X-Ray calls and leads (section 4).
- **Next slices** (not in this one):
  - **Chats:** Sales X-Ray's WhatsApp/Messenger/Instagram inbox, read-only. Needs a `chats:read` scope and `GET /v1/api/chats`.
  - **Coaching:** the coaching cards for a call. Needs `coaching:read`.

  Both add a scope first and then a tab, because the consent screen must show what is read.

## 4. How Pulse's AI uses Sales X-Ray through MCP

- **The server.** Sales X-Ray runs a remote MCP server at `/v1/mcp` (Streamable HTTP, MCP 2025-06-18).
  - It has seven tools: `whoami`, `list_calls`, `get_call`, `call_facts`, `list_leads`, `get_lead`, `add_lead`.
  - Each tool needs its API scope, and only the allowed tools are listed.
  - Without a token it answers 401 with `resource_metadata` (RFC 9728). Any MCP host (Claude, ChatGPT) can therefore discover Connect at `/.well-known/oauth-authorization-server`, register itself and sign the person in.
- **Pulse's gateway.** `POST /api/v0/sales-xray/mcp` forwards one JSON-RPC message to Sales X-Ray's `/v1/mcp` with the signed-in person's own token, refreshed as needed. Any assistant inside Pulse can use Sales X-Ray this way without holding a token.
- **Pulse's assistant ("Ask" on the app page).**
  - Pulse has no language-model layer of its own; its AI co-workers run `codex exec` on EA's included subscription. Ask runs it the same way:
    - `--ignore-user-config`, read-only, with the shell, browser, computer use, apps and skills off;
    - Sales X-Ray's `/v1/mcp` as its only MCP server.
  - The person's one-hour read token (`calls:read reports:read leads:read`) goes in the process environment (`bearer_token_env_var`), never in the prompt. The refresh token never leaves Pulse's API.
  - The answer comes back to the page. Nothing is written on the person's behalf: Pulse never asks for `leads:write`, so `add_lead` is not even listed.
  - Limits: 10 questions per person per 15 minutes, and two at a time.
  - It is off unless `PULSE_SALES_XRAY_ASK=1` (dev only first).

## 5. Plans and purchases

- **Who can connect.** Connecting needs only a Sales X-Ray account. What the person bought, or the organisation they were added to, decides what they see: Sales X-Ray applies its own plans, credits and limits to everything read through the connection, exactly as in its own app.
- **Pulse adds no billing.** Pulse never sees a price or a plan.
- **Running out.** A person whose Sales X-Ray access ends sees "Your Sales X-Ray access ended" in Pulse, with a link to Sales X-Ray.
- **Later.** Showing the plan name in Pulse needs a field in `/v1/api/me`. It is deliberately left out until the owner decides how plans appear (no prices on user screens).

## 6. What stays where

| | Sales X-Ray (AC server, AC Infisical) | Pulse (EA server, EA Infisical/keyring) |
|---|---|---|
| Calls, reports, facts, leads, chats | Kept here only | Read live for the person on screen; never stored or copied |
| OAuth client | Row in `integration_oauth_clients` (secret as SHA-256) | Client id, and the secret sealed with Pulse's document keyring |
| Tokens | SHA-256 only | Sealed per person (AES-256-GCM, bound to company and person) |
| Seal keys | `AC_INTEGRATIONS_SEAL_KEY` (not used by this flow) | `PULSE_DOCUMENT_KEY_FILE` |
| Audit | `integration.app_connected` and `integration.app_disconnected` in the workspace's chain | `sales_xray_connected` and `sales_xray_disconnected` events |

- **No copying.** Pulse caches no Sales X-Ray data: every list is read when the page asks, and the MCP answers go only to the asking person's screen.
- **No shared secrets.** Each side keeps its own keys. Nothing is copied between the two companies' Infisical projects.
- **No customer names in code.** Pulse is named only as a first-party app (our own product), in `first_party.py`.

## 7. Network

- **Server to server.** Pulse's server calls Sales X-Ray from its own server for `/v1/oauth/register`, `/v1/oauth/token`, `/v1/oauth/revoke`, `/v1/api/*` and `/v1/mcp`. These paths are bearer-token or public metadata and read no cookies.
- **Access on dev.** salesxray-dev sits behind Cloudflare Access, so it needs an Access bypass for those paths and for `/.well-known/oauth-*`. That is an owner dashboard step, the same kind as the Meta webhook bypass. Production is public already.
- **The consent page** (`/connect`) stays behind Access on dev; people sign in there as usual.

## 8. Switches and release

- **Sales X-Ray.** Everything here is additive and generic, with no migration. Organisation apps keep their old behaviour.
- **Pulse.**
  - **The module.** The `sales_xray` module is off unless the server switches it on: `PULSE_SALES_XRAY=1`, with `PULSE_SALES_XRAY_URL` set to the Sales X-Ray address for that environment (production by default).
  - **Ask** is separately off unless `PULSE_SALES_XRAY_ASK=1`.
  - **Release.** It ships to pulse-dev first through the laptop merge path (EST-1522). Staging and production follow EA's lane review and the train, under card EST-1363.
