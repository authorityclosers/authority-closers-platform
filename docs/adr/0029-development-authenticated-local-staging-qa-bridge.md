# ADR-029: Owner-approved development authenticated staging QA bridge

- Status: Accepted for development-only QA
- Date: 2026-09-03
- Owner: Platform and Security
- Supersedes: None; scoped exception to the host-only session topology in ADR-027

## Context

The learner UI uses same-origin `/v1` requests and host-only HttpOnly sessions.
The staging API must continue enforcing the staging learner origin for
cookie-authenticated unsafe methods. A staging `__Host-ac_session` therefore
cannot be placed in a localhost browser without breaking the cookie boundary,
and a browser-readable bearer token would create a materially weaker contract.

The owner-approved QA need is narrower: a tester must be able to run the real
learner UI with hot reload on localhost, explicitly sign in, and exercise the
real staging learner API and data. This must not broaden staging or production
behavior, expose provider/API credentials, or make local state authoritative.

## Decision

Implement a default-off bridge in the learner app's development `/v1` gateway.
It is active only when `NODE_ENV=development`,
`AC_DEV_AUTH_BRIDGE_ENABLED=true`, the configured browser origin is an exact
loopback HTTP(S) origin, and the upstream is exactly
`https://staging.authorityclosers.com`. Production, staging runtime, the API
host, production origins, pathful origins, and non-loopback binds are rejected.

The bridge follows the normal staging password-login flow. The upstream receives
the staging public-app `Origin` and the login body; the upstream's valid,
host-only `__Host-ac_session` is intercepted and retained only in an ephemeral
server-memory mapping. The browser receives a distinct random
`__Host-ac_dev_qa_session` with `Secure`, `HttpOnly`, `SameSite=Lax`, `Path=/`,
and no `Domain`. The staging cookie is never returned to the browser, written
to disk, or logged. The mapping is capped at eight sessions, expires after
eight hours, and disappears on process restart.

The combined launcher uses `learner.localhost` for this surface and
`admin.localhost` for the admin surface because host-only cookies are scoped by
host, not port. For defense in depth and compatibility with older plain
`localhost` sessions, the learner adapter recognizes only its own local handle,
and local API forwarding strips both learner and admin bridge-handle cookies.

Only the learner routes exercised by the current UI are allowlisted. The bridge
rejects direct staging cookies, `Authorization`, API-key headers, wrong or
missing unsafe-request origins, upstream redirects, upstream bearer response
headers, and a login response that drifts to a bearer-token contract. Logout
and upstream 401 responses remove the mapping and clear the local cookie.
The 1 MiB incoming-body reader observes the same bounded timeout and caller
abort as the upstream request.
Google, registration, recovery, verification, admin, internal, and arbitrary
proxy routes remain unavailable. No API, production, database, VPS, payment,
analytics, or audit authority is changed.

The local process is an explicit tester-owned trust boundary. If it is
compromised while the bridge is enabled, its in-memory mapping could be abused.
The mitigation is default-off activation, exact loopback binding, no
persistence/logging, an eight-hour cap, an eight-session cap, dedicated staging
test accounts, a visible UI warning, and revocation of the staging account or
session after suspected exposure.

## Alternatives

- Copying the staging cookie into localhost was rejected because it violates
  the host-only cookie boundary and makes a local browser carry staging state.
- Returning a bearer token or storing one in browser storage was rejected
  because JavaScript compromise would expose a reusable credential.
- Relaxing the staging `Origin`/CSRF checks was rejected because it weakens the
  deployed environment and makes the test bridge part of its security contract.
- Direct database/VPS edits or a local cache were rejected because they bypass
  API authorization and canonical audit/progress state.
- A dedicated isolated preview environment remains the preferred design for a
  broader or shared protected preview, but exceeds this narrow owner-approved
  QA slice and requires its own origin, sessions, database, and audit boundary.
- A provider-approved ephemeral session-exchange endpoint was not available in
  the current contract; adding one requires a separate API/security review.

## Consequences

- Testers can exercise the real learner UI and real staging data locally after
  explicitly signing in, while the staging API still sees its normal origin and
  session cookie.
- Restarting the local server invalidates all bridge sessions. Upstream 401 and
  logout also invalidate the mapping.
- The bridge is not a substitute for deployed staging tests and does not cover
  unsupported auth surfaces. ADR-030 separately governs the later, explicitly
  reviewed admin bridge; it does not broaden this learner adapter.
- The local process temporarily holds an opaque staging session in memory, so
  testers must use dedicated accounts, keep the port private, and revoke access
  after a suspected compromise.
- The bridge must stay outside staging/production builds and defaults.

## Reversal cost

Low to moderate. Removing the development route, environment variables, banner,
tests, runbook, and ADR restores the previous localhost/public-catalog-only
contract without migrating production sessions or data. Expanding the bridge's
scope would have a high reversal cost because it would become a new credential
and authorization contract.

## Evidence

- Controlled source manifest IDs: Master Index
  `1gC6BdFZ2LfjrpjM-qPKcX1qWMTUBSAXo3b-AlaOYqus`, API/MCP
  `1kWawS57AGVv7jT5Kp2V0Mk8kK0B6BwPzlG6KiAOtpt0`, Security
  `1rFTiq7BI4dpLLMIDacC8qMhpAbAmOct8W_I65Ydqbmw`, DevOps
  `1r1P2XdYSY8XhcgLR6icYqhlN1vEbqKagj8Rb16JpcJs`, QA
  `1DUx9JIHNC1KCR62Qso6KTFPoBxmfhU6GSuNqSl87hBg`, and ADR/Risk
  `1cNE-8DB0iX28U5IR_StkO-JGE2TPG-pbKn6LQ-bZSaY`.
- `docs/contracts/ENVIRONMENT_CONTRACT.md`
- `docs/adr/0027-use-host-only-same-origin-browser-sessions.md`
- `docs/runbooks/LOCAL_VPS_DATA_PREVIEW.md`
- `apps/learner-web/app/lib/dev-api-proxy.ts`
- `apps/learner-web/app/lib/dev-api-proxy.test.ts`
- `packages/python/ac_platform/http/auth.py`

## Trigger to revisit

Revisit if protected local QA becomes shared, remote, persistent, non-learner,
admin-surface, or production-connected; if the session contract changes; if
the staging provider requires OAuth or another non-password flow; or if a
provider-approved ephemeral session exchange becomes available.
