# Sales X-Ray developer platform (integrations)

Owner order, 19 Oct 2026: connecting any app to Sales X-Ray must be as simple as with top SaaS apps. That means no Infisical, password managers or ops steps per customer, and nothing named after any one customer.

## Slices
1. **API keys, the webhook and the hand-over in Organisation → Integrations.** Built (migration 0103).
2. **Connect:** "Connect to Sales X-Ray", OAuth 2.0 authorisation code with PKCE, a consent screen and scopes. Built.
3. **A command line and an MCP server** on the same API (`/developers/sx.py`), with the public `/developers` page. Built.
4. **Platform apps and the remote MCP** (20 Oct): apps register themselves (RFC 7591), each person connects their own account, and `/v1/mcp` serves the same tools over HTTP with Connect sign-in. Built; Pulse is the first such app (`SALES_XRAY_IN_PULSE.md`).

## Who
Integrations are for active owners and admins of a registered organisation. The live membership is checked on every request. Members and personal accounts do not see the tab. Platform admins see every organisation's integrations in Admin (`GET /v1/admin/integrations`) and can revoke a key.

## API keys (`integration_api_keys`)
- **Format.** `sxk_live_` on production and `sxk_test_` everywhere else, followed by 40 letters and digits (about 238 bits). A key works only in its own kind of environment.
- **Storage.** The key is shown once. We keep its SHA-256 (unique, used for lookup) and its first 13 characters for the list.
- **Each key has** a name, scopes and an expiry (30, 90 or 365 days, or never). It also records who made it, when it was last used (written at most once a minute), and when and by whom it was revoked.
- **Limits.** 25 active keys per organisation; 120 requests a minute per key.
- **Audit.** Making or revoking a key writes `integration.api_key_created` or `integration.api_key_revoked` to the organisation's audit chain, with the name, scopes and prefix, never the key.
- **Scopes:**
  - `calls:read`
  - `reports:read`
  - `leads:read`
  - `leads:write`
  - `webhooks:manage` (for the CLI and MCP)

## The API (`/v1/api`, `Authorization: Bearer sxk_…`)
| Route | Scope | What |
|---|---|---|
| `GET /me` | any | The organisation (or workspace), scopes, environment and reach; for a person's connection also the person and their role |
| `GET /calls?before=` | `calls:read` | Calls newest first, 50 a page, with each call's title and report link. The same visibility as the library: retention, deletion and test calls apply |
| `GET /calls/{id}` | `calls:read` | One call; with `reports:read` also its facts |
| `GET /calls/{id}/facts` | `reports:read` | The facts found in a call (`prospect-facts/1`). Withheld segments are never quoted |
| `GET /leads?stage=&offset=` | `leads:read` | Leads (`lead-desk/1` page) |
| `GET /leads/{id}` | `leads:read` | One lead |
| `POST /leads` | `leads:write` | Adds a lead through Lead Desk's own ingest (source `webhook`, label `API key <prefix>`). The same `external_id` again changes nothing |

Errors are `{"error": {"code", "message"}}`. A 401 carries `WWW-Authenticate: Bearer` and a 429 carries `Retry-After`.

**Reach.** An API key, or a token from an organisation's own app, sees what an owner sees. A token from a platform app acts as the person who connected it: their own calls and leads (a member), their team's (an owner or admin), or their own calls in a Personal workspace (leads answer `organisation_only`). The membership is read on every request; a person who left gets `403 access_ended`.

## Secrets the app keeps (`integration_secrets`)
- **Sealing.** AES-256-GCM under one platform key per environment, `AC_INTEGRATIONS_SEAL_KEY` (32 random bytes, base64url, in Infisical). Root sets it once per environment and gives it to the API and the partner-events runner. Nothing is set per customer.
- **Binding.** Each value has a fresh nonce and is bound to its row id, organisation and purpose, so a sealed value copied to another row does not open. `seal_key_id` names the platform key that sealed it, so the platform key can be rotated later.
- **Purposes:**
  - `webhook_signing`: made by the app (`whsec_` and 40 characters) and shown once.
  - `partner_key`: a key the organisation pastes for an app we call, such as a hand-over service key. Never shown again.
- **Changes.** The only later change to a secret is its one-time retirement.

## The webhook
It is the partner-events endpoint from 0096. It keeps the same table, events, signing (`X-SX-Signature: t=…,v1=…`), retries and runner.
- **Secret reference.** A webhook made in the app names its secret `AC_PARTNER_WEBHOOK_SECRET__SEALED_<32 hex>`. This fits the existing `secret_ref` pattern, so the 0096 and 0102 tables are unchanged. `delivery.read_secrets_for` reads that name from the sealed store; every other name still comes from the environment, so the operator CLI keeps working.
- **Save.** The first save makes the signing secret. A later save (new address, events or facts profile) keeps it. Saving over an endpoint AC set up by hand replaces it with an app-managed endpoint and a new secret.
- **Rotate.** A second secret signs alongside the first (two `v1=` values). "My app uses the new secret" makes it the only one and retires the old one.
- **Send test event.** One signed fictional `sx.test.v1` goes out now, with the same public-address check and no redirects. The page shows what came back.
- **Delivery log.** The last 50 events (analysis and lead events) with state, tries and the last answer, never the payload. An event that stopped retrying can be sent again.
- **Turn off.** Disables the endpoint and retires its secrets.

## The hand-over
When a lead is won, Sales X-Ray calls the organisation's own app (`POST <app>/api/v1/service/customers/handover`, 0102).
- **Set up in Integrations.** The owner or admin enters the app's address (the path is added when missing) and pastes the service key their app issued. The key is sealed as a `partner_key` and never shown again; the page shows its last four characters.
- **What goes.** They approve the optional parts and, per part, the exact form question each answer comes from (`lead_events.validate_lead_fields`).
- **Changes.** It is the 0102 recipient: superseded, never edited, audited. Changing the address or parts keeps the key; a new key retires the old one; Turn off retires it.

## Connect (OAuth 2.0 + PKCE)
- **Apps.** An organisation registers its own apps in Integrations (`sxc_` client id; for an app with a server, an `sxcs_` secret shown once). Return addresses are exact: https, or http on 127.0.0.1/localhost.
- **Consent.** `/connect` checks the app and address before showing anything; a wrong app or address is shown, never redirected. The open organisation's owner or admin approves the scopes.
- **Codes and tokens.** Codes are single-use for 10 minutes and bound to the client, address and PKCE S256 verifier. `sxa_` access tokens last 1 hour on `/v1/api`; `sxr_` refresh tokens last 30 days and are replaced on use. A code or refresh token used twice ends the connection. `POST /v1/oauth/token` and `POST /v1/oauth/revoke` (RFC 7009). Everything is stored as SHA-256.
- **Disconnect.** In Integrations, or by a platform admin.

### Platform apps (20 Oct)
- **Self-registration.** `POST /v1/oauth/register` (RFC 7591): `client_name`, `redirect_uris`, `token_endpoint_auth_method` (`none` for a public client, otherwise a secret is returned once), `grant_types`. Names that read as Sales X-Ray or Authority Closers are refused; 10 registrations an hour per address and 200 in all.
- **Discovery.** `GET /v1/oauth/metadata`, and the web app serves the same at `/.well-known/oauth-authorization-server` (RFC 8414) and `/.well-known/oauth-protected-resource/v1/mcp` (RFC 9728), only on Sales X-Ray's own hosts.
- **Consent.** Any signed-in person approves a platform app for their own account in the workspace they have open (Personal or an organisation; not the operations workspace). The screen says whether the app is checked: a first-party app (`first_party.py`, Pulse) only on its own host for this environment; any other shows a caution and its return host. An MCP host that asks for no scope gets `calls:read reports:read leads:read`.
- **Safety.** A replayed code ends only that person's connection. People list and remove their own connections at `GET /v1/me/connected-apps` and `POST /v1/me/connected-apps/{id}/revoke` (audited as `integration.app_disconnected`); owners and admins still see every connection in Integrations.

## Command line and MCP
`/developers/sx.py` is one Python file, standard library only, that reads the key from `SX_API_KEY`. Commands: `me`, `calls`, `facts`, `leads`, `lead` and `add-lead`. `sx.py mcp` is an MCP server on stdio with tools `whoami`, `list_calls`, `call_facts`, `list_leads`, `get_lead` and `add_lead`. The public `/developers` page documents everything above, with signature checks in Node.js and Python.

**Remote MCP (`/v1/mcp`).** Streamable HTTP (MCP 2025-06-18; 2025-03-26 and 2024-11-05 accepted), one JSON answer per message, 202 for a notification, 405 on GET (no server stream). Bearer `sxa_` or `sxk_`; without one, 401 with `resource_metadata`. A foreign `Origin` is refused. Tools: `whoami`, `list_calls`, `get_call`, `call_facts`, `list_leads`, `get_lead`, `add_lead`, each needing its API scope and listed only when allowed; they read through the same `Reader` as `/v1/api`, so reach and withheld segments are identical.

## Admin
`GET /v1/admin/integrations` (`sx-integrations-admin/2`) returns:
- counts;
- per organisation, with its kind: keys by prefix with who made and revoked them, webhooks by host with last delivery, last status and failures in 24 hours, and connected apps.

Platform admins can revoke a key, turn off a webhook or disconnect an app. Each action is audited in the organisation's own chain and answers with the updated row.

## Not yet
- Chats and coaching through the API and MCP (`chats:read`, `coaching:read`), for the Pulse app's next tabs.
- A Settings screen for the person's own connected apps (the API is there).
- Webhook management through the API (`webhooks:manage`).
- More than one webhook per organisation: 0096 keeps one active endpoint.
