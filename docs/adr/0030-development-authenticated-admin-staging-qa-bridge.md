# ADR-030: Development authenticated admin staging QA bridge

- Status: Accepted for development-only QA
- Date: 2026-09-04
- Owner: Platform and Security
- Supersedes: ADR-029's admin exclusion only; the learner decision remains intact

## Context

The admin staging surface is protected by Cloudflare Access and by the
product's host-only session, tenant membership, role, and permission checks. A
local admin UI needs realistic staging behavior for supervised UI work, but
copying either remote cookie into a localhost browser, adding a service-token
bypass, or weakening upstream Origin checks would create a new authority path.

The current Access application allows the approved admin email identity and has
no service-token policy. The product already supports password login and
server-owned `/v1/me` plus `/v1/context` authorization. The bounded need is to
compose those existing controls for one loopback-only development process
without changing staging or production.

## Decision

Add a default-off admin `/v1` development adapter. It is active only under
`next dev` when all of the following are valid:

- `AC_DEV_ADMIN_AUTH_BRIDGE_ENABLED=true`;
- the browser origin is an exact HTTP(S) loopback origin;
- the upstream is exactly `https://admin-staging.authorityclosers.com`; and
- `AC_DEV_ADMIN_ACCESS_JWT` contains a current Cloudflare Access user JWT.

The combined launcher retrieves the Access JWT from `cloudflared` after normal
human Access authentication and passes it only through the admin child-process
environment. It does not print or persist the JWT, place it in a command-line
argument, send it to the learner process, or return it to the browser. A
service token is neither created nor accepted.

Cloudflare Access proves only edge transport. The local admin login form then
uses the normal staging password-login endpoint. The adapter intercepts the
upstream host-only `__Host-ac_session` and independently reads `/v1/me` and
`/v1/context`. It creates a local mapping only if both responses agree on the
same person and selected tenant, the membership role is owner, admin, or
support, and both contain `admin_surface`. A learner or inconsistent context is
rejected and the unmapped upstream session is revoked best-effort.

The browser receives a distinct random `__Host-ac_dev_admin_qa_session` with
`Secure`, `HttpOnly`, `SameSite=Lax`, `Path=/`, and no `Domain`. The server-side
mapping is memory-only, capped at four sessions, expires after eight hours, and
is removed on logout or upstream 401. Malformed, expired, and restart-stale
local cookies are actively cleared.

The adapter allowlists only bridge health, password login/logout, `/v1/me`,
`/v1/context`, and exact current first-slice admin mutation paths for publish,
correction, grant, job retry, and recovery reconciliation. It rejects arbitrary
paths and queries, direct staging/Access cookies, bearer/API-key/service-token
headers, wrong origins, redirects, oversize bodies, malformed upstream session
cookies, and non-admin identity contexts. Mutations still rely on the staging
API's canonical tenant, permission, reason, idempotency, audit, and external
effects-hold checks.

The admin shell is visible in development only when the complete bridge
configuration validates (or the pre-existing explicit inert preview flag is
set). Production continues to require the server-owned internal admin context;
no deployment configuration, database, VPS, provider, payment, analytics, or
canonical record is changed.

## Alternatives

- Copying Cloudflare or product cookies into localhost was rejected because it
  moves remote credentials into the browser and breaks host-only boundaries.
- A Cloudflare service token was rejected because the existing Access policy
  does not grant it and it would bypass the approved human identity control.
- Direct use of the staging API host, Origin rewriting in browser code, or CORS
  relaxation was rejected because it weakens the deployed boundary.
- Direct database/VPS access was rejected because it bypasses product
  authorization, tenancy, audit, and immutable state transitions.
- A dedicated isolated preview deployment remains appropriate if this workflow
  becomes shared, remotely reachable, persistent, or broader than the current
  allowlist.

## Consequences

- A tester performs two explicit checks: Cloudflare Access for edge transport,
  then product password login for admin authorization.
- The local server temporarily holds opaque remote credentials in memory. It
  must remain loopback-only and be stopped/revoked after suspected exposure.
- Existing absent admin read models and gated provider/media capabilities stay
  unavailable. Their P0s block those capabilities, not this development bridge.
- Restarting the admin server invalidates local handles and requires sign-in
  again; Access expiry requires restarting the combined launcher.

## Reversal cost

Low to moderate. Remove the admin route adapter, login/notice components,
launcher variables, tests, and this ADR. No production session, database, or
deployment migration is involved.

## Evidence

- Controlled source IDs: Master Index
  `1gC6BdFZ2LfjrpjM-qPKcX1qWMTUBSAXo3b-AlaOYqus`, BRD
  `1HEp7QN4u3c_636uACznnkruYHhGYHAJWXH7Dlfjybpk`, AC-IMP-00
  `10tKbAIJWONFNTzK2-NHffy4h1wKgoQP7VdJH_K2eR-A`, AC-IMP-01
  `1JVnCjDdE79YseM-1PuhvW00xcoicwmhoHtUvEuKKrdU`, AC-IMP-03
  `1ncsRMiMMiQ39tCn7dV3vpqwUnirY06BgSuVdm_BuIFo`, AC-IMP-04
  `1gQnsY1JjphpmOmfyCRZkfI-p0TWZjF1PkY1xF744Gnc`, and AC-IMP-05
  `1Vvf1wCA_JjrJQwhkTsgyDM_9179G4M899pWWc3-UdXw`.
- Relevant controlled specifications: API/MCP
  `1kWawS57AGVv7jT5Kp2V0Mk8kK0B6BwPzlG6KiAOtpt0`, Security
  `1rFTiq7BI4dpLLMIDacC8qMhpAbAmOct8W_I65Ydqbmw`, Admin
  `12-VjN02jx8M7S8wJrZLcl4OwLcXIFGXKu74wxdJrWuY`, DevOps
  `1r1P2XdYSY8XhcgLR6icYqhlN1vEbqKagj8Rb16JpcJs`, QA
  `1DUx9JIHNC1KCR62Qso6KTFPoBxmfhU6GSuNqSl87hBg`, ADR/Risk
  `1cNE-8DB0iX28U5IR_StkO-JGE2TPG-pbKn6LQ-bZSaY`, and AC-UXA-01
  `1ZRyNPkkfc8DsBAlpKE9ksb6Oi-nB9BX-`.
- Implementation and tests:
  `apps/admin-web/app/lib/dev-api-proxy.ts`,
  `apps/admin-web/app/lib/dev-api-proxy.test.ts`,
  `scripts/Start-LocalStagingBridge.ps1`, and
  `tests/infra/test_local_staging_bridge.py`.

## Trigger to revisit

Revisit before enabling a service identity, adding admin read/proxy breadth,
sharing the bridge, binding beyond loopback, accepting OAuth callbacks locally,
or connecting any production environment.
