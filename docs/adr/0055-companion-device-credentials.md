# ADR 0055: Companion device credentials

- Status: Proposed; CTO review required before companion card 4
- Date: 2026-10-08
- Amends: [ADR 0027](0027-use-host-only-same-origin-browser-sessions.md)

## Context

Sales Xray companion apps need to upload consented recordings and read submission
status and notifications without depending on a web page's layout. An embedded
web view cannot be the Google sign-in surface. ADR 0027 reserves the API host for
non-browser clients but rejects browser-readable bearer credentials and keeps
browser sessions host-only and same-origin.

[AUT-1556](/AUT/issues/AUT-1556), card 3 of
[AUT-1553](/AUT/issues/AUT-1553), fixes the credential design below. EA's companion
gateway, `/connect` approval and device settings are reference evidence, not an
AC authorization policy. Its broader business routes and sensing permissions do
not transfer to Sales Xray. This ADR records a bounded exception to ADR 0027;
it implements no routes, storage, clients or infrastructure changes.

## Decision

### 1. Pair in the signed-in browser

The app calls pairing `start` with its device name and platform. The response
contains an 8-character code from an unambiguous alphabet and a separate,
cryptographically random private poll secret. Pairing codes expire 10 minutes
after creation and are single use. Persist only SHA-256 hashes of the code and
poll secret; never retain either plaintext value in storage, logs or audit data.

The app opens `/connect` in the external browser. The signed-in person sees the
code, device name, platform, request time and expiry, and explicitly chooses
**Approve** or **This wasn't me**. Approval binds the device to that person and
the selected workspace after checking active membership. Denial ends the pairing
attempt and issues no credentials. Approval does not extend the original expiry.

Only the holder of the private poll secret can collect the approved token pair.
The displayed code, browser session or knowledge of a pairing identifier cannot
collect it. The browser never receives the device tokens. Approval/denial and
token collection each use atomic, single-use transitions so races, expiry and
repeated polling cannot issue a second token pair. A failed or expired attempt
requires a new pairing request.

### 2. Opaque tokens with rotating refresh families

Access and refresh tokens are opaque cryptographically random strings, never
JWTs. Store only their SHA-256 hashes and server-side device/family metadata.
An access token expires after 15 minutes. Every successful refresh consumes the
current refresh token and issues a new access/refresh pair atomically.

A refresh family expires after 30 days idle or 90 days from its original issue,
whichever comes first. Rotation resets only the idle window, never the absolute
limit. Retain spent-token hash evidence for reuse detection through the family's
lifetime. Reuse of a spent refresh token revokes the whole family, including its
access tokens; no member of that family is accepted on the next request. Clients
serialize refresh calls to avoid accidental reuse. Expiry requires pairing again.

### 3. Amend ADR 0027 only for isolated companion credentials

Bearer authentication is accepted only on `/v1/native/*` and only for an exact
method-and-route allowlist. That prefix is a namespace, not a wildcard grant or
generic proxy into `/v1`. The Python API owns admission and authorization.

Credentials belong only to the companion's trusted native execution context:
Android OS keystore-backed storage, iOS/macOS Keychain, Windows Credential Manager,
or private Chrome extension storage. For Chrome, the extension service worker
owns credential use; tokens are not exposed to content scripts or visited pages.
No web page or web view can read a token, including through an injected bridge,
local/session storage, a URL, messages or a JavaScript response.

Authentication modes do not combine. A native request with a bearer credential
ignores cookies, including when the bearer is invalid; it never falls back to a
cookie session. A browser cookie-session request ignores bearer credentials and
still requires the ordinary session and write-origin checks. Cookies cannot
authorize native resource routes. Outside the native allowlist, a bearer grants
no access. Existing browser APIs, host-only cookie attributes, same-origin
routing, CSP and server-side Google OAuth in ADR 0027 remain in force.

### 4. Exact resource allowlist

These are the only companion resource operations. `{submission_id}` and
`{device_id}` are validated identifiers, not arbitrary path suffixes. Existing
resource ownership and workspace authorization checks apply to every operation.

| Method | Native route                                                             | Authority                                                                                  |
| ------ | ------------------------------------------------------------------------ | ------------------------------------------------------------------------------------------ |
| GET    | `/v1/native/conversation/acquisition/upload-policy`                      | Read the current upload policy.                                                            |
| GET    | `/v1/native/conversation/acquisition/submissions`                        | List the person's submissions in the bound workspace.                                      |
| GET    | `/v1/native/conversation/acquisition/submissions/{submission_id}`        | Read one authorized submission.                                                            |
| PUT    | `/v1/native/conversation/acquisition/submissions/{submission_id}/source` | Upload source with the existing policy and consent checks and required capture provenance. |
| GET    | `/v1/native/notifications`                                               | Read notifications visible to the bound person and workspace.                              |
| POST   | `/v1/native/notifications/read`                                          | Mark the person's visible notifications read.                                              |
| POST   | `/v1/native/devices/{device_id}/revoke`                                  | Revoke only the device authenticating this request.                                        |

Source PUT retains `X-Upload-Policy` and `X-Upload-Consent: accepted` as today,
and requires `X-Capture-Source` from the enum below. Existing upload limits,
submission-id/SHA retry behavior and consent verification remain authoritative.
The new header records provenance; it does not grant consent or start analysis.

Credential lifecycle operations have their own exact allowlist:

| Method | Native route             | Credential                                                                 |
| ------ | ------------------------ | -------------------------------------------------------------------------- |
| POST   | `/v1/native/pair/start`  | No existing credential; strict pairing rate limit.                         |
| POST   | `/v1/native/pair/poll`   | Private poll secret for this pairing attempt.                              |
| POST   | `/v1/native/refresh`     | Refresh token; spent-token reuse revokes the family.                       |
| POST   | `/v1/native/web-session` | Active access token for the requesting device; issues only a handoff code. |

These routes grant no resource permissions and cannot use cookies as a
substitute for their own credential. Pair approval/denial and the browser device
list/revoke controls use ordinary signed-in browser sessions.

Never admit plans, billing, credits, consent settings, account or organisation
administration, or deletion. Report downloads, source reads and other sibling
routes are not implied by submission GET. New native operations require an
explicit allowlist change and review. Companion apps never approve plans or
spend credits; those actions retain their existing web authorization and consent.

### 5. Bind and revoke at the canonical membership boundary

Device credentials are bound to user + workspace at approval. Check current
membership, device revocation and family status on every authenticated native
request, including refresh and web-session issue. Do not cache an authorization
fact for the 15-minute access-token lifetime. Removing membership or revoking a
device takes effect on the next request, even with an unexpired access token.

People can see their devices and revoke them from the signed-in browser.
Removing a member revokes their devices bound to that workspace and all related
token families. A device cannot switch workspace by changing request parameters;
a different binding requires a new approval. Native own-device revoke cannot
revoke another device or operate as workspace administration.

### 6. One-time handoff to a normal web session

An active device may request a one-time web-session code, bound to that device,
user and workspace. It expires after 60 seconds and is single use. The app's web
view exchanges it through top-level navigation to the approved application host,
not through page JavaScript or a cross-origin API token transfer. Consume the
code atomically and recheck device, family and membership before issuing the
normal `__Host-ac_session` session cookie.

The cookie is Secure, HttpOnly, SameSite=Lax and host-only, with no `Domain`, as
required by ADR 0027. The handoff code is not an access or refresh token and must
not appear in logs, analytics or referrers. The web view receives only its normal
cookie session; native bearer credentials stay in protected device storage.
Google sign-in runs in the external browser during pairing, so the web view does
not attempt Google's embedded sign-in. The handoff does not bypass ordinary web
session authorization or approve any plan, consent setting or credit spend.

### 7. Capture provenance without inventing historical evidence

Every new submission records `capture_source`. For native source PUT, validate
the required `X-Capture-Source` and persist its enum value alongside the submission.
Web upload and browser capture paths also record their applicable value.

The complete enum is `web_upload`, `browser_display_capture`,
`android_dialer_pickup`, `android_share`, `ios_share`, `ios_recorder`,
`desktop_recorder`, `desktop_watch_folder`, `chrome_tab`.

Existing rows remain NULL, displayed as **before provenance**. There is no
backfill, inference from filenames or platforms, or rewrite of historical audit
evidence. Capture source describes the upload's origin; it is not proof of
recording consent, canonical progress, payment or scoring authority.

### 8. Rate limits and an off-by-default kill switch

Apply per-address and per-device rate limits. Pairing start has the strictest
limit; polling, refresh and authenticated resource traffic have separate bounded
budgets. Rate-limiter keys and receipts must not expose credentials. Exhaustion
rejects the request rather than bypassing the limit or falling back to cookies.

`AC_NATIVE_API_ENABLED` is off by default in every environment. When off, native
admission, pairing, refresh and web-session issue are unavailable. Browser device
revocation remains available. Enabling the switch is a separate governed change;
this ADR grants no environment activation or infrastructure permission.

### 9. Append-only audit events

Record pair approve, pair deny, refresh-reuse revoke, device revoke and
web-session issue as append-only audit events. Include the relevant actor,
workspace, device/family or pairing reference, time and outcome. Member removal
records its resulting device revocations. Never include plaintext codes, poll
secrets, tokens, session credentials or recording contents. Corrections supersede
history; no event is overwritten or deleted.

### 10. Keep the existing activation gates

AC-GOV-AUD-001 remains required before store release, live recording or
auto-upload. Auto-upload needs its own versioned consent; pairing approval and
upload consent do not silently authorize it. The 1-year retention rule is
unchanged. Consent, provenance, provider and professional gates still apply to
real-call processing; no autonomous AI scoring is authorized by this ADR.

Apps never approve plans or spend credits. Signing keys live only in Infisical.
A dev/staging Cloudflare Access bypass, if separately authorized, is limited to
the exact `/v1/native/` path namespace on the API host. It cannot cover all `/v1`,
an application host or production, and it never replaces product authentication.

## Alternatives

- Embedded Google sign-in and DOM-based fake uploads cannot provide a reliable
  native credential and upload boundary.
- Browser-readable bearer tokens or a parent-domain session cookie would broaden
  the exposure rejected by ADR 0027.
- JWTs or non-rotating refresh tokens would weaken immediate server-side family
  revocation and reuse detection.
- Copying EA's entire gateway allowlist would authorize unrelated business
  operations; only the AC resource operations above are admitted.

## Consequences

Companions can upload and observe results under revocable workspace authority.
Browser and native sessions stay distinct. Subsequent cards must implement
pairing/device/family storage, native admission, handoff and provenance, with
negative tests for cookie fallback, disallowed routes, collection without the poll secret,
expiry, concurrent collection/refresh, spent-token reuse and membership removal.
Those implementation and migration changes are outside this documentation card.
CTO review is required before card 4 starts; this proposal is not implementation
or activation evidence. There is no dev screen check for this docs-only change.

## Reversal cost

Disable native admission, revoke device families and outstanding handoff codes,
and require browser sign-in. Later storage changes need reviewed migrations.
Preserve audit history and recorded capture provenance; do not backfill legacy
rows or broaden cookie scope to accommodate rollback. Browser sessions retain
ADR 0027's topology.

## Evidence

- [AUT-1556 fixed CTO decisions](/AUT/issues/AUT-1556) and
  [AUT-1553 companion plan](/AUT/issues/AUT-1553).
- AC source pin: `99e8934ed530a67f90dd7dac76888580de57fbf9`.
  [ADR 0027](0027-use-host-only-same-origin-browser-sessions.md),
  `packages/python/ac_platform/http/conversation_submissions.py` and
  `packages/python/ac_platform/http/product_updates.py` establish the current
  browser, upload and notification contracts.
- Local read-only study: `/home/acdev/scratch/ea-study/reports/r9-native-companion.md`
  sections 1–3, SHA-256
  `feeaac222bdbf4446cb7cd4a65579fabe76a90718e5bc16fd3757252bb9ec8f4`.
- EA companion copy: `/home/acdev/scratch/ea-study/ea-companion/`.
  Source hashes pin the inspected reference files:
  - `apps/web/app/api/native/gateway.mjs`:
    `d81d44ac28f6d658cc59f84c807368a7265d80466a6f0e5fc0cddb1c8969c0de`.
  - `apps/web/app/connect/approval.tsx`:
    `88905ce44f0aa5d4c4df8ac8a55f42c007e6a570cb22412461ff84d860d09dd5`.
  - `apps/web/app/settings/devices.tsx`:
    `21c24f25b4d6ace56f7cd216a1e856e250e0a769ab37c49b52ea4716986de033`.
    The copy omits EA's API pairing/token store; it is not evidence that AC's
    server-side expiry, revocation or reuse controls already exist.

## Owner

CTO owns this security design and its review. Admin Lead records the fixed
decisions in this card; later assigned companion cards implement them.

## Supersedes

No ADR is superseded. This explicitly amends
[ADR 0027](0027-use-host-only-same-origin-browser-sessions.md) for isolated native
bearer credentials and device-bound web-session handoff. ADR 0027's own text is
unchanged and its browser session requirements continue to apply.

## Trigger to revisit

Revisit before extending native routes, token lifetime, storage or workspace
scope; exposing credentials to a page or web view; changing handoff topology,
consent or retention; or proposing a broader ingress bypass. Store publishing,
live recording and auto-upload still require their separate gates.
