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

The default learner/admin ports are `3000` and `3001`. If either belongs to
another workspace, leave that process alone and select two free loopback ports:

```powershell
pwsh -NoProfile -File scripts/Start-LocalStagingBridge.ps1 -LearnerPort 3100 -AdminPort 3101
```

Use the exact ports printed by the launcher. The isolated hosts remain
`learner.localhost` and `admin.localhost`; only their loopback ports change.
Only one tracked bridge instance may run from a worktree at a time. Stop it
before changing ports so the process record and in-memory Access session cannot
be orphaned.

The launcher binds both Next dev servers to `127.0.0.1`. If the current
Cloudflare Access user session is absent or expired, it opens the normal Access
browser login. The Access JWT is captured in memory and passed only to the
admin child process. It is not printed, stored in an env file, placed in a
command line, written to the PID record, or exposed to the learner process.

On the default ports, startup succeeds only after both probes pass:

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

When alternate ports are selected, replace only `3000` and `3001` in those
probe/login URLs with the exact learner and admin ports printed by the launcher.

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
capabilities require their existing governance gates. The bounded progressive
delivery bridge below transports only already-approved staging media; it does
not activate a provider or approve missing lesson media.

### Approved progressive media on localhost

When the authenticated bridge is explicitly enabled, the existing server layout
passes only its exact local origin to a transport context. The player must first
validate the unchanged HTTPS staging descriptor and expiration envelope, then
register eligible MP4/WebM and caption sources through authenticated same-origin
`POST /v1/dev-bridge/media`. Signed sources travel only in the bounded JSON body,
never in a localhost URL. The response contains positional opaque local paths
and expiry, not tokens. Native media is withheld until registration completes.
The browser carries its normal local HttpOnly bridge handle; the staging session
and source registry remain in server memory. Do not copy a signed URL or staging
cookie into browser storage, logs, a command, or a document.

The byte gateway accepts authenticated GET/HEAD on
`/v1/dev-bridge/media/{opaque-locator}` with **no query** and one bounded byte
range. A locator is not a credential: it resolves only within its current local
session generation, and staging still verifies the original signed source and
staging cookie. The legacy token-in-local-query route is denied. Registration is
limited to 12 distinct sources / 64 KiB per request, 30 requests per minute per
session, 64 entries per session, and eight sessions. Entries expire no later than
the original grant (whose validated envelope is at most one hour). Logout, 401,
session replacement, eviction, expiry, and restart drop associated entries.
Reconnect revalidates the original descriptor through the normal activity API
before obtaining a fresh transport registration. Failed/expired authority is not
repaired locally; no fallback to a remote signed source or new progress write is
introduced. Video/WebVTT responses stream with cancellation after headers.

HLS playlists and child rewriting are intentionally unsupported. An approved
progressive fallback can be used; a manifest-only descriptor remains unavailable.
No provider upload or database state is enabled by this path. The page must
withhold unsupported transport rather than silently requesting a remote URL
without its normal staging host-only cookie.

Keep the local dev port private. Restarting the bridge clears its memory-only
session mappings. Opted-in framework request/fetch logs must not record the
signed token query; browser network tools may still display the live request
and should not be copied/exported unredacted. Release evidence must use sanitized
status/range/byte observations without signed URLs or credentials. This local
bridge is not production deployment or a replacement for staging acceptance.

#### Next development trace privacy (required before signed-media QA)

`logging: false` suppresses ordinary console URL logs but **does not suppress
Next's `.next/dev/trace` files or its unconditional exception loggers**. Opaque
local locator URLs and the explicit media-only Node HTTPS upstream adapter are
the privacy boundary. Do not route media through patched global fetch: its HMR
cache can log a full outgoing signed URL when a background body read fails, even
with `cache: no-store`. The managed launcher additionally sets
`NEXT_TRACE_SPAN_THRESHOLD_MS=9007199254740991` only in the learner child's
environment, before Next starts; its workers inherit it. Do not set this inside
`next.config.ts`, where tracing may already be imported, or as a machine-wide
environment variable. Next config refuses an enabled learner bridge without
this exact startup guard or when the installed Next version differs from the
reviewed **16.3.3** pin. Ordinary non-bridge development and production do not
require this guard and keep their normal logging behavior.

This is an **internal, undocumented Next control**, not a stable public API.
An upgrade must revalidate the installed tracing implementation and update the
explicit version fence only after the real reporter regression and synthetic
HTTP/trace check pass. The installed-runtime test includes a leaking negative
control, automatic batch flush, forced flush, inherited child environment, and
the maximum duration Next permits. It is not sufficient to inspect stdout alone.

After introducing this guard an already-running unguarded learner process may
stop on config reload. Restart it through the managed launcher; do not weaken
the gate to restore availability. Restarting clears local login handles. Preserve
existing logs and traces as restricted local diagnostic evidence; do not export
their contents, and do not delete files as a substitute for preventing writes.
Only synthetic invalid no-cookie probes are permitted until the actual running
process has passed the trace-file check. The current implementation evidence
records any blocked restart or pending runtime check explicitly.

The learner launcher also clears its child-only `NODE_DEBUG` mask before Node
starts. Native HTTPS diagnostics can otherwise print signed paths and cookies.
An enabled bridge refuses unsafe cached or current HTTP/HTTPS debug settings
before any media request is constructed. Clearing the variable later inside
application code is insufficient: Node caches its initial mask. Use the managed
launcher after this change; do not enable credential-bearing diagnostic capture
or copy diagnostic contents into release evidence.

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
