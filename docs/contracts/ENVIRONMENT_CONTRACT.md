# Environment contract

Production configuration is injected from Infisical at process start. Git contains names and safe local defaults only.

| Variable                                   | Owner             |    Required outside local | Purpose                                                 |
| ------------------------------------------ | ----------------- | ------------------------: | ------------------------------------------------------- |
| `AC_ENVIRONMENT`                           | release           |                       yes | `development`, `staging`, or `production` behavior gate |
| `AC_RELEASE_ID`                            | release           |                       yes | immutable Git-derived release identity                  |
| `AC_DATABASE_URL`                          | runtime identity  |                       yes | least-privilege application connection                  |
| `AC_DATABASE_MIGRATOR_URL`                 | deploy identity   |               deploy only | schema migration connection                             |
| `AC_SESSION_TOKEN_PEPPER`                  | identity security |                       yes | opaque session lookup hashing                           |
| `AC_OAUTH_TRANSACTION_SECRET`              | identity security |                       yes | browser OAuth transaction authentication                |
| `AC_EMAIL_CHALLENGE_SECRET`                | identity security |                       yes | email challenge lookup/encryption key material          |
| `AC_GOOGLE_OAUTH_CLIENT_ID`                | identity provider |                       yes | Google web OAuth client identifier                      |
| `AC_GOOGLE_OAUTH_CLIENT_SECRET`            | identity provider |                       yes | Google web OAuth client secret                          |
| `AC_LEARNER_CONSENT_VERSION`               | legal/product     | learner registration only | exact accepted invitation/consent document version      |
| `AC_PUBLIC_LEARNER_TENANT_ID`              | tenancy operator  | learner registration only | exact active tenant receiving self-directed learners    |
| `AC_OPERATIONS_TENANT_ID`                  | security/operator |    before effects release | exact control tenant for audited global job recovery    |
| `AC_EXTERNAL_SIDE_EFFECTS_HOLD`            | recovery operator |                       yes | blocks provider effects after restore                   |
| `AC_EMAIL_PROVIDER`                        | provider policy   |               worker only | `fake` until Resend is explicitly enabled               |
| `AC_RESEND_API_KEY`                        | email provider    |        worker when Resend | worker-only Resend credential                           |
| `AC_RESEND_FROM`                           | email/provider    |        worker when Resend | reviewed transactional sender identity                  |
| `AC_OTEL_EXPORTER_OTLP_ENDPOINT`           | telemetry         |                       yes | trace/metric collector endpoint                         |
| `AC_PUBLIC_APP_URL`                        | edge              |                       yes | learner origin and redirect allowlist source            |
| `AC_ADMIN_APP_URL`                         | edge              |                       yes | admin origin and redirect allowlist source              |
| `AC_API_URL`                               | edge              |                       yes | canonical API origin                                    |
| `AC_DEV_API_ORIGIN`                        | local development |                        no | loopback API or exact staging public-catalog preview    |
| `AC_DEV_AUTH_BRIDGE_ENABLED`               | local development |                        no | explicit opt-in for the authenticated staging QA bridge |
| `AC_DEV_AUTH_BRIDGE_ORIGIN`                | local development |                        no | exact loopback browser origin for the QA bridge         |
| `AC_DEV_AUTH_BRIDGE_UPSTREAM_ORIGIN`       | local development |                        no | exact staging learner origin for the QA bridge          |
| `AC_DEV_ADMIN_API_ORIGIN`                  | local development |                        no | loopback API for ordinary admin development             |
| `AC_DEV_ADMIN_AUTH_BRIDGE_ENABLED`         | local development |                        no | explicit opt-in for the admin staging QA bridge         |
| `AC_DEV_ADMIN_AUTH_BRIDGE_ORIGIN`          | local development |                        no | exact loopback admin browser origin                     |
| `AC_DEV_ADMIN_AUTH_BRIDGE_UPSTREAM_ORIGIN` | local development |                        no | exact Access-protected staging admin origin             |
| `AC_DEV_ADMIN_ACCESS_JWT`                  | local process     |                        no | ephemeral Cloudflare Access user JWT; never file-backed |
| `AC_API_HOST`                              | edge              |                       yes | canonical public API host and health probe Host         |
| `AC_INTERNAL_API_HOST`                     | release           |                       yes | reserved app-network-only API DNS name                  |

## Media provider foundation

The media provider is disabled by default. The following variables describe a
private S3/MinIO-compatible composition contract; they do not provision a
bucket or contact a provider. Setting `AC_MEDIA_PROVIDER_ENABLED=true` is
validated only when the complete storage, delivery, CORS, quota, and TTL set is
present and the exact `AC-GOV-AUD-001` and `GAP-MEDIA-001` references are
supplied. Those strings are evidence labels, not authorization. The shipped
staging and production composition rejects enabled media settings, and no
immutable audited activation record or provider transport is currently
composed; provider activation is therefore blocked in this slice.

| Variable                                                                                                                                                    | Purpose                                                                                                                              |
| ----------------------------------------------------------------------------------------------------------------------------------------------------------- | ------------------------------------------------------------------------------------------------------------------------------------ |
| `AC_MEDIA_PROVIDER_ENABLED`                                                                                                                                 | validated provider intent; defaults to `false` and is rejected by shipped staging/production composition                             |
| `AC_MEDIA_PROVIDER`                                                                                                                                         | `unconfigured`, `s3`, or `minio`                                                                                                     |
| `AC_MEDIA_STORAGE_ENDPOINT`, `AC_MEDIA_STORAGE_APPROVED_ENDPOINT_HOSTS`                                                                                     | HTTPS S3 API endpoint and exact approved endpoint-host allowlist; loopback, link-local, private, and unapproved targets are rejected |
| `AC_MEDIA_STORAGE_BUCKET`, `AC_MEDIA_STORAGE_REGION`                                                                                                        | bounded bucket and region identifiers                                                                                                |
| `AC_MEDIA_STORAGE_ACCESS_KEY_ID`, `AC_MEDIA_STORAGE_SECRET_ACCESS_KEY`                                                                                      | reserved provider credentials; no shipped composition currently injects or uses them                                                 |
| `AC_MEDIA_DELIVERY_ORIGIN`, `AC_MEDIA_CORS_ORIGINS`                                                                                                         | exact HTTPS playback origin and comma-separated CORS origins (local loopback HTTP is allowed for tests)                              |
| `AC_MEDIA_GOVERNANCE_REFERENCE`, `AC_MEDIA_GAP_REFERENCE`                                                                                                   | exact evidence references required by the validated config; they do not activate a provider                                          |
| `AC_MEDIA_UPLOAD_TTL_SECONDS`, `AC_MEDIA_PLAYBACK_TTL_SECONDS`                                                                                              | bounded short-lived upload/playback lifetimes                                                                                        |
| `AC_MEDIA_MAX_UPLOAD_BYTES`, `AC_MEDIA_QUOTA_*`, `AC_MEDIA_MAX_RENDITIONS`, `AC_MEDIA_MAX_PROCESSING_OUTPUT_BYTES`, `AC_MEDIA_MAX_PROCESSING_CAPTION_BYTES` | upload and worker safety limits, including caption bytes                                                                             |
| `AC_MEDIA_ALLOW_RANGE_REQUESTS`                                                                                                                             | explicit single-range progressive delivery policy                                                                                    |

Credentials must come from the deployment secret mechanism and must never be
written to Git, logs, telemetry, or this contract.

Canonical staging origins are `https://staging.authorityclosers.com`,
`https://admin-staging.authorityclosers.com`, and
`https://api-staging.authorityclosers.com`. Canonical production origins are
the `app`, `admin`, and `api` first-level subdomains. Deep staging subdomains are
not used because the free Cloudflare Universal SSL certificate does not cover a
second subdomain label.

The non-secret release profile additionally fixes `AC_COMPOSE_PROJECT`,
`AC_STATE_ROOT`, `AC_API_HOST`, `AC_INTERNAL_API_HOST`, and three
environment-specific edge aliases.
The workflow-produced `release-images.env` binds the full Git SHA to exact image
IDs and private-registry provenance digests. Staging and production promotion
must reuse that identical file.

`AC_DEV_API_ORIGIN` is read only by the learner app's `next dev` proxy. It may
name loopback for normal local development or the exact canonical staging API
origin for anonymous `GET /v1/programs` and `GET /v1/programs/{slug}`. The
remote mode forwards only the request's negotiation headers and the original
`Origin`, strips cookies, authorization, proxy metadata, and arbitrary headers,
rejects private endpoints and all mutations, and rejects upstream redirects.
Blank values are treated as unset. It is invalid in staging/production and
must never contain credentials or a production origin. Protected real-data
tests run on the deployed staging origin unless the owner-approved development
bridge below is explicitly enabled.

The authenticated local staging QA bridge is a separate, development-only
exception for real learner UI testing. It activates only when
`NODE_ENV=development`, `AC_DEV_AUTH_BRIDGE_ENABLED=true`,
`AC_DEV_AUTH_BRIDGE_ORIGIN` is an exact loopback origin such as
`http://localhost:3000`, and `AC_DEV_AUTH_BRIDGE_UPSTREAM_ORIGIN` is exactly
`https://staging.authorityclosers.com`. It is never valid in staging or
production, never accepts a public/non-loopback bind, and never accepts the API
host or a production origin as its upstream.

The bridge uses the normal staging password-login route and staging's normal
same-surface `Origin` check. It consumes the upstream `__Host-ac_session` only
inside the local server process, maps it to an ephemeral random local handle,
and returns only a separate `__Host-ac_dev_qa_session` cookie with
`Secure`, `HttpOnly`, `SameSite=Lax`, `Path=/`, and no `Domain`. The staging
cookie is never returned to the browser, written to disk, logged, or accepted
from a browser request. The in-memory mapping is capped at eight sessions and
expires after eight hours; a local server restart invalidates it. The bridge
forwards only the allowlisted learner routes used by the real UI, rejects
bearer/API-key credentials and staging cookies, requires the exact configured
browser origin for unsafe methods, and marks responses with
`X-AC-Dev-Data-Mode: staging-authenticated`. Google, registration, recovery,
verification, admin, internal, and arbitrary proxy routes remain unavailable.

The admin local staging bridge is a separate development-only adapter governed
by ADR-030. It activates only when `NODE_ENV=development`, the explicit admin
bridge flag is true, its browser origin is an exact loopback origin, its
upstream is exactly `https://admin-staging.authorityclosers.com`, and the local
process has a current Cloudflare Access user JWT. The launcher obtains that JWT
from `cloudflared` after the already-approved human Access login and passes it
only in the admin child process environment. It is never checked into an env
file, placed in a command argument, returned to the browser, written to the PID
record, or shared with the learner process.

Cloudflare Access transport does not grant product access. The tester must also
complete the normal staging password login, after which the bridge verifies
`/v1/me` and `/v1/context` for the same person, a selected tenant, an
owner/admin/support role, and `admin_surface` permission before it creates an
ephemeral localhost handle. The remote host-only product session and Access JWT
remain inside the admin dev process. The mapping is capped at four sessions,
expires after eight hours, and is cleared on logout, upstream 401, or process
restart. Only the current first-slice admin endpoints are allowlisted; browser
credentials, arbitrary routes, production origins, and direct API/DB/VPS paths
remain rejected.

`pnpm dev:staging` is the supported combined learner/admin launcher. It requires
Node 24, pnpm 11, PowerShell 7.4+, and `cloudflared`; binds both Next servers to
`127.0.0.1`; performs public-catalog and Access-transport health checks; and
stores only process IDs, timestamps, and logs under ignored `.tmp` state. It
does not start Docker, connect to a database, or inject production/provider
credentials. Use `pnpm dev:staging:down` to stop only the tracked process trees.

This is a tester-owned process boundary, not a production security boundary:
anyone who can compromise the opted-in local development process could use its
in-memory staging session mappings. Keep the bridge default-off, bind only to
loopback, use a dedicated staging test account, do not expose the dev port,
and revoke the staging account/session if the local process is suspected to be
compromised. See ADR-029, ADR-030, and the local QA runbook for the threat model and
operational procedure.

Compose assigns only the environment's reserved `AC_INTERNAL_API_HOST` to the
API container on the isolated application network:
`api.staging.ac.internal.invalid` or
`api.production.ac.internal.invalid`. The admin server's internal URL is
exactly `http://<AC_INTERNAL_API_HOST>:8000`; its adapter rejects any host/URL
mismatch or alternate origin before making a request and does not override
Node's transport-owned `Host` header. Loss of the alias produces a `.invalid`
DNS failure rather than a plaintext request to public DNS. `AC_API_HOST`
remains the canonical public API host used by the edge and API health probe.

Activated staging and production also fix the cookie names to
`__Host-ac_session` and `__Host-ac_oauth_transaction`. The API emits them only
with `Secure`, `HttpOnly`, `SameSite=Lax`, `Path=/`, and no `Domain`, and rejects
missing, malformed, or duplicate raw security-cookie fields before identity or
OAuth callback resolution.

The three identity secrets must be mutually independent, non-default values of
at least 32 bytes. Secrets such as database passwords, OAuth credentials,
signing keys, provider tokens, and R2 credentials are intentionally absent. No
client-exposed variable may contain a secret.

The Google OAuth client ID and secret are mandatory for activated staging and
production. Test and development may omit the pair, but supplying either value
requires both values and whitespace-only values are treated as empty.

Password registration fails closed when either `AC_LEARNER_CONSENT_VERSION` or
`AC_PUBLIC_LEARNER_TENANT_ID` is absent. Learner Google registration is
permitted only when the learner explicitly accepts the exact required consent
before OAuth starts and that version is authenticated inside the signed,
single-use OAuth transaction. The callback rejects absent, changed, stale, or
replayed consent state before provisioning. Existing-person Google
authentication remains subject to the same tenant and membership checks.
The tenant UUID is an operator-selected reference to an existing active tenant;
the application never invents a tenant, changes an existing role, or reactivates
an inactive membership. Admin-surface Google login never auto-provisions a
learner membership.

The public learner tenant must be distinct from `AC_OPERATIONS_TENANT_ID`.
Membership role is singular per person and tenant, so reusing the operations
tenant would leave an operations owner unable to satisfy the learner-only
self-enrollment boundary. The dedicated tenant is created or validated only by
the documented idempotent `python -m ac_platform.bootstrap --public-learner`
command; the command creates no person or membership. Registration/login then
creates the exact learner membership after verified, current consent.

For the exact published global program slug `authority-closers-free-course`,
an explicit start action may convert that recorded consent into a canonical
eligibility fact under `AC-FREE-SELF-ATTESTATION-v1`. Existing positive facts
are reused and never overwritten; negative, expired, wrong-course, stale-
consent, non-learner, inactive or unverified inputs fail closed. The fact and
enrollment are committed together, and the policy evidence is retained in
enrollment provenance and audit output.

`AC_OPERATIONS_TENANT_ID` names an existing active control tenant; the
application never creates it. An empty environment may omit this reference
only while `AC_EXTERNAL_SIDE_EFFECTS_HOLD=true`. The worker then remains
unavailable and tenantless retry/recovery fails closed. Before releasing the
hold, deployment settings require the exact control tenant. A global
identity-email job can be retried or reconciled only while an owner has
selected this exact tenant and holds the separate global operations
permissions. The immutable idempotency marker and the privileged action are
written into that tenant's audit chain. Ordinary tenant operators remain
unable to act on tenantless jobs.

`AC_EMAIL_PROVIDER=resend` additionally requires both `AC_RESEND_API_KEY` and
`AC_RESEND_FROM`. Compose binds all three variables only to the worker. The API
and migrator receive no mail-provider selector or credential and retain the
application's default `fake` provider. The key must never be exposed to a web
image or client variable. The checked-in staging and production profiles remain
`fake`; switching a profile to Resend is a reviewed provider activation, not an
ad-hoc runtime toggle.
