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
behavior must be tested on the deployed staging learner origin. A host-only
secure staging session cookie cannot be safely reused by localhost, and the API
must continue rejecting localhost as the Origin for staging mutations.

Forbidden workarounds include copying cookies, rewriting Origin, disabling CSRF
checks, exposing a VPS database/API port, or making a local browser cache
canonical. If a future protected local preview is required, build a dedicated
isolated preview environment with its own origin, session, database, and audit
boundary.
