# Local UI with VPS-backed catalog data

Status: bounded development contract. This runbook does not create a new
authority boundary and does not make VPS state authoritative.

## Supported modes

The learner web app exposes one same-origin `/v1` development proxy. It is
disabled outside `next dev` and accepts only these upstreams:

1. `http://127.0.0.1:8000` or another loopback origin for the normal local API.
   Local authenticated reads and mutations retain the browser-supplied Origin
   and local cookie contract.
2. `https://api-staging.authorityclosers.com` for anonymous published-catalog
   reads only: `GET /v1/programs` (optionally with one canonical `limit` from
   1 through 100) and `GET /v1/programs/{slug}` (one canonical encoded slug,
   no query, at most 120 characters).

The staging mode strips cookies and authorization, removes upstream
`Set-Cookie`, forwards only `Accept`, `Accept-Language`, and the original
`Origin`, rejects upstream redirects, rejects every mutation, and rejects
private reads before any request reaches staging. It exists so localhost can
render real published VPS catalog data without exporting a staging session or
opening a VPS port.

## Run the staging catalog preview

In a local, uncommitted environment file for `apps/learner-web`, set:

```dotenv
AC_DEV_API_ORIGIN=https://api-staging.authorityclosers.com
```

Then run the learner app with the repository's normal `next dev` command. The
response header `X-AC-Dev-Data-Mode: staging-public-catalog` identifies data
returned through this mode.

Do not put credentials, session cookies, SSH keys, or provider secrets in this
variable or in Git.

## Protected real data

Authenticated profile, onboarding, progress, enrollment, evidence, and session
behavior may be tested from localhost only through the owner-approved
development bridge below. Otherwise use the deployed staging learner origin. A
host-only secure staging session cookie cannot be safely reused by localhost,
and the API must continue rejecting localhost as the Origin for staging
mutations.

## Authenticated staging QA bridge

The bridge is default-off, available only to `next dev`, and creates a separate
local host-only session handle. The real staging session remains server-side in
ephemeral memory; it is not copied into the browser, written to disk, or
logged. Use a dedicated staging learner account and treat every mutation as a
real staging-data change.

In an uncommitted local environment file for `apps/learner-web`, set:

```dotenv
AC_DEV_AUTH_BRIDGE_ENABLED=true
AC_DEV_AUTH_BRIDGE_ORIGIN=http://localhost:3000
AC_DEV_AUTH_BRIDGE_UPSTREAM_ORIGIN=https://staging.authorityclosers.com
```

Leave `AC_DEV_API_ORIGIN` blank or set it to a loopback API. Run the normal
learner `next dev` command and open `http://localhost:3000/login`. Sign in
explicitly with the staging test account through the normal password-login
form. A persistent banner says `Development bridge • staging data`, and
responses identify `X-AC-Dev-Data-Mode: staging-authenticated`.

The bridge's local session expires when the dev server restarts or after eight
hours. Restarting the server drops its in-memory mapping; revoke the remote
staging session if the process or machine may have been exposed. Google,
registration, recovery, verification, admin, and unsupported routes remain on
deployed staging. Do not expose the dev port, add credentials or cookies to
Git, or use production accounts.

Forbidden workarounds include copying cookies, rewriting Origin, disabling CSRF
checks in staging, exposing a VPS database/API port, or making a local browser
cache canonical. If a broader or non-learner protected local preview is
required, build a dedicated isolated preview environment with its own origin,
session, database, and audit boundary.
