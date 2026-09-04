# Local learner and admin UI with staging-backed data

Status: bounded development contract. This runbook creates no new authority
boundary and does not make VPS or local state authoritative.

## Preferred combined workflow

Prerequisites are Node 24, pnpm 11, PowerShell 7.4+, `cloudflared`, access to the
existing `AC Admin Staging` Cloudflare Access application, and dedicated
staging learner/admin credentials. From this worktree, run:

```powershell
pnpm dev:staging
```

The launcher binds both Next dev servers to `127.0.0.1`. If the current
Cloudflare Access user session is absent or expired, it opens the normal Access
browser login. The Access JWT is captured in memory and passed only to the
admin child process. It is not printed, stored in an env file, placed in a
command line, written to the PID record, or exposed to the learner process.

Startup succeeds only after both probes pass:

- `http://learner.localhost:3000/v1/programs?limit=1` returns the staging public
  catalog with `X-AC-Dev-Data-Mode: staging-public-catalog`.
- `http://admin.localhost:3001/v1/dev-bridge/health` confirms Cloudflare Access can
  reach the staging product API boundary while the product session still
  reports sign-in required.

Use `http://learner.localhost:3000/login` for the learner and
`http://admin.localhost:3001/login` for the admin. Both use the normal staging
password authentication contract and create separate ephemeral cookies on
distinct local hosts. Account creation, Google sign-in, email verification, and password
recovery continue on the deployed learner staging origin because their
provider callbacks and one-time links are origin-bound.

Stop only the tracked process trees with:

```powershell
pnpm dev:staging:down
```

Logs remain under ignored `.tmp/local-staging-bridge`. They must not contain
passwords, session cookies, Access JWTs, or other credentials.

## Learner modes

The learner web app exposes one same-origin `/v1` development proxy. It is
disabled outside `next dev` and accepts only these upstreams:

1. `http://127.0.0.1:8000` or another loopback origin for ordinary local API
   development.
2. `https://api-staging.authorityclosers.com` for anonymous published-catalog
   reads only.
3. `https://staging.authorityclosers.com` for the explicitly enabled,
   authenticated development bridge.

The anonymous staging mode strips cookies and authorization, forwards only
negotiation headers and Origin, removes upstream `Set-Cookie`, and rejects
redirects, private reads, and every mutation. It permits only
`GET /v1/programs` with one canonical limit from 1 through 100 and
`GET /v1/programs/{slug}` with one bounded canonical segment.

For a learner-only anonymous catalog preview, set this in an uncommitted local
environment file for `apps/learner-web`:

```dotenv
AC_DEV_API_ORIGIN=https://api-staging.authorityclosers.com
```

Run the normal learner `next dev` command. Never put credentials, session
cookies, SSH keys, or provider secrets in this variable or in Git.

### Authenticated learner bridge

The combined launcher sets the development-only learner bridge variables. For
manual setup, use only an uncommitted local process environment:

```dotenv
AC_DEV_AUTH_BRIDGE_ENABLED=true
AC_DEV_AUTH_BRIDGE_ORIGIN=http://learner.localhost:3000
AC_DEV_AUTH_BRIDGE_UPSTREAM_ORIGIN=https://staging.authorityclosers.com
```

The real host-only staging session remains in ephemeral server memory and maps
to a distinct `__Host-ac_dev_qa_session` browser handle. The mapping is capped
at eight sessions, expires after eight hours, and disappears on restart,
logout, or upstream 401. Malformed or restart-stale cookies are cleared.

Only the current learner UI contract is allowlisted. It includes canonical
profile/onboarding, public catalog, enrollment, learning collection/detail,
calendar/insights, activity draft/evidence, certificate, and avatar routes.
The collection is exactly `GET /v1/learning?limit=50` with an optional bounded
cursor. Google, registration, recovery, verification, admin, internal, and
arbitrary routes remain on deployed staging. Playback and media-provider
capabilities remain unavailable until their existing governance gates are met.

## Authenticated admin bridge

The combined launcher is the supported setup. The admin dev server first uses
the existing Cloudflare Access user identity to cross the staging edge, then
requires normal product email/password login. A successful login is not enough:
`/v1/me` and `/v1/context` must agree on person and tenant and prove an
owner/admin/support membership with `admin_surface` permission. A learner
account cannot be mapped into a local admin session.

The browser receives only `__Host-ac_dev_admin_qa_session`. The upstream
`__Host-ac_session`, `CF_Authorization`, bearer credentials, API keys, and
service-token fields are rejected at the browser boundary. The allowlist is
limited to bridge health, password login/logout, `/v1/me`, `/v1/context`, and
the implemented first-slice publish, correction, grant, retry, and reconcile
mutations. Every mutation still runs through staging's canonical authorization,
tenant, reason, idempotency, audit, and effects-hold rules. Missing read models
remain explicitly unavailable instead of being fabricated.

The local admin mapping is memory-only, capped at four sessions, and expires
after eight hours or when the process restarts. An upstream 401 or logout
clears it. Access expiry requires restarting the combined workflow. If local
process memory may have been exposed, stop the bridge and revoke both staging
and Cloudflare Access sessions.

## Forbidden workarounds

Do not copy remote cookies, rewrite Origin in browser code, disable staging
CSRF checks, expose a VPS database/API port, make a browser cache canonical,
use production accounts, or activate provider/media work through this bridge.
This workflow never connects directly to PostgreSQL, seeds production, deploys,
or changes production configuration.

If protected local QA becomes shared, remotely reachable, persistent, or
broader than these exact allowlists, build a dedicated isolated preview
environment with its own origin, session, database, and audit boundary.
