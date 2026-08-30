# ADR-027: Use host-only, same-origin browser sessions

- Status: Accepted
- Date: 2026-08-30
- Owner: Platform and Security
- Supersedes: None

## Context

Authority Closers has three application hosts and an existing WordPress site on
the apex domain. A parent-domain session cookie would be sent to every matching
subdomain and would make compromise or misconfiguration of an unrelated host a
session-boundary concern. Sending browser credentials directly to the API host
would instead require a shared parent cookie or a browser-readable token.

Google sign-in also needs state, nonce, PKCE, replay, redirect, and surface
binding without placing provider credentials or a durable authorization fact in
the browser.

## Decision

- Learner and admin sessions are opaque, Secure, HttpOnly, SameSite=Lax,
  host-only cookies. No session cookie has a `Domain` attribute.
- Caddy routes `/v1/*` on `app.authorityclosers.com` and
  `admin.authorityclosers.com` to the API before routing other paths to Next.js.
  Authenticated browser requests therefore remain same-origin.
- Google uses the server-side authorization-code flow with PKCE. The callback
  returns to the initiating learner or admin host, and Google registers one
  callback URI for each surface.
- A durable, expiring authorization transaction is created before redirect.
  PostgreSQL stores hashes of state, nonce, and PKCE verifier plus audience,
  purpose, optional person binding, status, and expiry. The HttpOnly callback
  cookie carries an HMAC-authenticated transaction reference and one-time
  values; callback consumption is locked and atomic.
- `api.authorityclosers.com` remains available for health, internal integration,
  and future non-browser clients. Browser Content Security Policy permits
  connections only to the current origin.
- The WordPress apex is never in the application session-cookie trust boundary.

## Alternatives

- A `.authorityclosers.com` cookie was rejected because it expands credential
  exposure to the apex and every subdomain.
- Browser-readable bearer tokens were rejected because JavaScript compromise
  would expose reusable credentials and complicate revocation.
- A single API-host callback followed by token transfer was rejected because it
  requires a cross-origin credential handoff.
- Cloudflare Access alone was rejected as product identity; it protects admin
  ingress but does not replace canonical people, memberships, sessions, or
  learner authorization.

## Consequences

- Learner and admin surfaces hold separate sessions even when both resolve to
  the same canonical person. Admin login is intentionally explicit.
- Google Cloud must retain both exact callback URIs.
- Every browser API route must be reachable through the same-origin `/v1`
  gateway; introducing a direct API-origin browser call requires a new review.
- Unsafe cookie-authenticated methods still require an allowlisted `Origin`.
- Caddy route ordering, cookie attributes, OAuth transaction persistence, and
  OpenAPI composition are release-blocking tests.

## Reversal cost

Moderate to high. Changing cookie scope or callback topology would require a
coordinated gateway, Google OAuth, application, CSP, session invalidation, and
security-test migration. Existing sessions should be revoked during reversal.

## Evidence

- `packages/python/ac_platform/http/auth.py`
- `packages/python/ac_platform/http/auth_transactions.py`
- `packages/python/ac_platform/http/identity_provider.py`
- `infra/vps-foundation/compose/foundation/Caddyfile`
- `tests/unit/http/`
- `tests/integration/test_identity_postgresql.py`
- `tests/infra/test_application_release.py`

## Trigger to revisit

Revisit only if an approved native client, a separately isolated admin domain,
or a controlled API gateway requires a different credential topology. Traffic
growth alone is not a reason to broaden cookie scope.
