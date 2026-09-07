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

## 2026-09-07 addendum: authenticated local progressive media transport

The owner requested actual approved staging lesson playback through the existing
local learner session. This addendum is a bounded transport extension, not media
provider activation. The server-issued descriptor remains unchanged: its original
HTTPS source and signed grant envelope still pass the player's existing scope
and expiry checks before any transport mapping.

The root server layout resolves the existing development bridge configuration.
It serializes only the exact non-secret loopback browser origin into a scoped
React context. No session, public environment bypass flag, provider credential,
or global browser authorization configuration is introduced. In opted-in bridge
mode the final playback/caption transport maps only the exact staging public
origin and canonical `/v1/media/playback/{encoded-object-key}?token=...` path to
that same configured/current loopback origin. An unsupported mapping returns
null and must withhold playback, never fall back to the original upstream URL.

Only authenticated GET and HEAD are added to the gateway allowlist. Keys use
the canonical structured immutable object namespace, have at most 512 decoded
characters, and cannot contain double encoding, traversal, ambiguous encoding,
empty components, credentials, fragments, or extra query fields. The query is
one bounded application media token. Parsing does not validate its signature or
grant: staging rechecks the existing session, tenant, enrollment, activity,
binding, immutable version, signed key, and token expiration on every byte
request. Existing local handles, memory-only staging cookies, origin checks,
logout/401 invalidation, and production/default-off gates are unchanged.

Progressive MP4/WebM and WebVTT are the first transport slice. A key need not
have an extension because canonical originals and caption IDs may not have one;
successful response MIME and declared length are separately allowlisted.
Manifests and HLS child URL rewriting are not enabled. GET/HEAD may forward only
one validated bounded `bytes=start-end` or `bytes=start-` range; suffix/multipart
and malformed ranges are refused. The backend already registers both methods.

Bodies stream with backpressure rather than buffering the video in application
memory. Request cancellation and downstream cancellation remain attached until
stream completion, and bounded header/read/whole-stream timeouts are retained.
Only safe media response headers cross the boundary. Redirects, unexpected MIME,
inconsistent range/length, and upstream error bodies fail closed with sanitized
responses. No token-bearing URL, cookie, or upstream exception is logged or
persisted by this adapter. Framework request/fetch logging for this opted-in
development surface must also suppress signed URLs.

This transport requires its own implementation/security regression evidence and
independent review before handoff. It does not claim successful real playback
until the player hook, normal local session, and actual approved staging media
have been tested together. Provider uploads, HLS, real-call processing, direct
database access, production access, and autonomous learning evidence remain
outside this addendum.

### Trace-privacy correction to the 2026-09-07 media addendum

Independent review disproved console-only suppression as a complete privacy
boundary: installed Next 16.2.11 attaches the full incoming URL to handle-request
and memory-usage spans, and its JSON reporter persists those spans in
`.next/dev/trace` regardless of `logging: false`. A synthetic no-cookie 401
request appeared twice after automatic reporter batching. No actual media token
was used in that probe. The earlier stdout-only observation remains valid but
does not establish trace privacy.

The managed launcher sets Next's internal `NEXT_TRACE_SPAN_THRESHOLD_MS` to
`9007199254740991` in the learner child before Next bootstrap. In this exact
installed version, `Span.stop` rejects durations above `Number.MAX_SAFE_INTEGER`
microseconds and reports only when duration exceeds threshold milliseconds times
1000. The configured comparison cutoff is finite and strictly greater than
every permitted duration; it therefore suppresses every normally recorded span.
Next workers inherit the same startup environment. This does not patch a
dependency, change globals after import, remove logs, or disable production
observability. Build-worker trace replay is not a new supported local delivery
mode; the managed development launcher remains webpack-based.

This control is undocumented and version-dependent. Enabled local bridge config
fails closed unless the threshold is exact and the installed Next version is
16.2.11. Any framework upgrade requires fresh installed-runtime and HTTP/trace
privacy proof before changing the fence. Tests exercise the installed reporter
in fresh processes with a leaking negative control, more than 100 events,
explicit flush, maximum valid duration, and inherited subprocess environment.
Actual running-server HTTP evidence is separate and must not be inferred from
the installed-module regression. A blocked restart blocks local media QA, not
the wider product or staging deployment.

### Superseding media URL boundary: session-bound opaque registry

Further independent review demonstrated that tracing suppression is insufficient
as a complete privacy boundary. Next's outer request-handler catch unconditionally
prints an incoming request URL if a handler escapes; its patched-fetch HMR cache
can separately print an outgoing fetch URL after a background body-read failure.
Both demonstrations used only synthetic tokens and no network authorization.
The earlier console and trace observations remain preserved, not reclassified
as successful privacy acceptance.

This decision **replaces the token-in-local-query mapping described above**.
The original HTTPS activity descriptor remains unchanged and passes all existing
player authority/expiry checks. The client submits a bounded authenticated
same-origin JSON POST to `/v1/dev-bridge/media`, and receives only opaque local
locator paths plus expiry. Native video, captions and quality URLs remain absent
until registration succeeds. Source URLs exist only in the POST body and memory.
Only GET/HEAD without any query can use a locator. The old signed local route
is denied; there is no compatibility or remote-source fallback.

The registry belongs to the existing in-memory local session object, not an
independent credential store. An opaque random locator cannot authorize a byte
request without the same valid current local session. Registration rechecks the
session generation after asynchronously reading its body, including replacement
with an identical staging-cookie string. Logout, upstream 401, replacement,
eviction, expiry and restart invalidate the associated registry. Every byte
request still sends the original source and normal staging cookie for backend
signature, session, tenant, enrollment, binding, object and grant checks.

Bounds are 12 distinct sources and 64 KiB per registration, 12-second body
timeout, 30 attempts/minute per session, 64 registry entries per session and
eight sessions. Registration validates exact fixed-staging canonical URL/key
syntax plus the AC-MEDIA type, playback kind, key agreement, nonempty scope
metadata, safe timestamps, at most 30 seconds future clock skew, and at most
one-hour grant envelope. This metadata parsing can reject but cannot validate
a signature or grant new authority. Registry expiry cannot exceed signed expiry
or the local session. Reconnect first rechecks the existing activity descriptor
and then invalidates/re-registers its client mapping, with stale asynchronous
responses withheld and no automatic progress write.

Signed upstream media bytes use an explicit server-only Node HTTPS transport,
not Next's instrumented global fetch. It preserves the exact staging target,
manual redirects, safe request headers, cancellation and Web Stream response
contract. The gateway's previously reviewed Range, MIME, size, backpressure,
timeout and sanitized-error gates remain in force. Ordinary JSON API traffic
keeps its existing fetch path. The trace threshold and validated-version fence
remain defense-in-depth; they are not the sole privacy boundary.
