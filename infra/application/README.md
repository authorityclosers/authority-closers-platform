# Application release contract

This directory packages the G1 modular monolith without making a workstation,
source checkout, or browser authoritative. Staging and production are isolated
Compose projects with separate PostgreSQL state and stable edge aliases. The
only valid release ID is the full reviewed Git commit from a verified archive.

## Trust and state boundaries

- The learner, admin, API, worker, and PostgreSQL containers expose no host
  ports. Only the existing loopback Caddy service can reach web/API services on
  the external `ac_edge` Docker network.
- Staging uses `staging.authorityclosers.com`,
  `admin-staging.authorityclosers.com`, and
  `api-staging.authorityclosers.com`. These are first-level names so they remain
  inside Cloudflare Universal SSL coverage. Production uses the canonical
  `app`, `admin`, and `api` names.
- Environment profiles fix distinct Compose project names, state roots, public
  origins, trusted API hosts, and `ac_edge` aliases. No generic alias is shared
  between staging and production.
- On each environment's isolated `app` network, the API service owns only its
  reserved, non-public `AC_INTERNAL_API_HOST`: `api.staging.ac.internal.invalid`
  or `api.production.ac.internal.invalid`. The admin server calls exactly
  `http://<AC_INTERNAL_API_HOST>:8000`; its adapter rejects any other host or URL
  before network access and lets Node derive the wire `Host` from that canonical
  URL. It forwards exactly one syntactically valid `__Host-ac_session` cookie
  and no other browser cookies. If the Docker alias is absent, `.invalid` DNS
  fails instead of falling back to a public plaintext destination. The separate
  public `AC_API_HOST` remains the API health and edge-host contract.
- PostgreSQL is reachable only on the internal data network. The owner,
  migrator, runtime, and backup credentials are distinct Infisical secrets.
- The modular monolith runtime role deliberately retains table-level
  `SELECT`, `INSERT`, `UPDATE`, and `DELETE` because its reviewed persistence
  adapters span the identity, tenancy, catalog, enrollment, learning,
  certificate, and operations modules in one database. That credential is a
  process trust boundary, not a user or authorization identity: every request
  still resolves its actor, tenant, membership, permission, enrollment, and
  immutable catalog version in application code. PostgreSQL independently
  enforces structural, provenance, append-only, and published-content
  invariants. The runtime owns no relations or functions and receives no
  schema/database/temporary-object creation, DDL, `TRUNCATE`, `REFERENCES`, or
  `TRIGGER` privilege. Splitting module-specific credentials is deferred until
  module processes and transaction ownership are split; claiming row-level
  actor isolation from the shared runtime credential would be false.
- Session tokens are stored only as peppered digests. The token pepper, OAuth
  transaction secret, and email-challenge secret are three independent
  required Infisical values and never enter an image, repository, URL, log, or
  browser-readable cookie. Email challenge lookup uses a keyed hash; the
  delivery token is encrypted only for the durable post-commit worker.
- Activated staging and production use exactly `__Host-ac_session` and
  `__Host-ac_oauth_transaction`. Both are `Secure`, `HttpOnly`, `SameSite=Lax`,
  scoped to `Path=/`, and carry no `Domain` attribute. The API reads raw Cookie
  fields and rejects missing, malformed, or duplicate security cookies before
  actor or callback resolution. Caddy routes `/v1/*` on
  `app.authorityclosers.com` and `admin.authorityclosers.com` to the API before
  their Next.js fallbacks, so Google callbacks return to the initiating
  surface without extending trust to the WordPress apex or the other surface.
- Google authorization state is persisted before redirect as a one-time,
  expiring database transaction. Only hashes of state, nonce, and PKCE verifier
  are durable; the HMAC-authenticated browser transaction references its UUID.
- Uvicorn does not accept forwarded proxy headers. Application authorization
  never derives a person, tenant, role, permission, or resource owner from
  caller-controlled proxy or request fields.
- The in-process anonymous-operation limiter trusts `CF-Connecting-IP` only
  from the exact versioned `AC_TRUSTED_PROXY_ADDRESSES` peer. The foundation
  pins Caddy to `172.18.0.2` on the reviewed `172.18.0.0/16` bridge and validates
  both values before activation. It is a bounded,
  fail-closed defense for the single Uvicorn worker shipped here, not a
  distributed limit across multiple API replicas. Keep Cloudflare edge limits
  as the fleet-wide control before adding workers or replicas.
- Runtime containers are non-root, read-only, capability-free, PID/memory/CPU
  bounded, and write only to bounded tmpfs mounts.
- External side effects remain held by default. A migration does not start or
  release the worker.
- Persistent database files live below
  `/srv/authority-closers/state/application/<environment>/postgres`, which is
  included in the
  encrypted Restic source set. A crash-consistent file copy is not a substitute
  for the release backup/restore procedure.
- Before first start, the release installer creates that PostgreSQL directory
  with owner `999:999` and mode `0700`. The database container runs as that
  fixed non-root identity and cannot repair an incorrectly owned host path.
- The pinned PostgreSQL 18 image mounts that host directory at
  `/var/lib/postgresql`; the image creates its major-versioned cluster below
  that parent. Do not restore it into the legacy `/var/lib/postgresql/data`
  mount layout.
- Local and TCP database authentication are both SCRAM-SHA-256. Readiness is a
  real authenticated SQL probe against `ac_platform` and verifies the three
  least-privilege service roles; a listening-but-uninitialized server never
  becomes healthy.
- The web build uses `--frozen-lockfile --trust-lockfile`: hosted validation
  performs the supply-chain policy check, and the verified release archive then
  treats that exact lockfile as trusted while pnpm still verifies package
  integrity against its content hashes.

## Release construction

The manual `Application validation` workflow first runs the complete validation
job on GitHub-hosted infrastructure. It then builds Linux/AMD64 images, publishes
an immutable full-SHA tag to private GHCR, and records both registry provenance
digests and the OCI transport manifest digests used by the VPS. Before upload,
each transport manifest is hash-verified and required to reference the exact
reviewed image config. This avoids storage-driver-dependent local image IDs while
preserving a cryptographic build-to-transport binding. A rerun is allowed only
when an existing full-SHA tag resolves to the identical image config.
The checksummed `release-images.env` has an exact fixed contract: each API,
learner, and admin image records a local Docker config ID in `AC_*_IMAGE`, its
OCI transport-manifest digest in `AC_*_TRANSPORT_DIGEST`, and its immutable GHCR
digest in `AC_*_REGISTRY_DIGEST`, plus one `AC_RELEASE_ID` and one
`AC_MIGRATION_HEAD`. Local config IDs are the only values used to start services;
the two digest families are retained as independently named provenance.
Release packaging is globally serialized. After the candidate bundle is fully
verified, the workflow refuses upload when all retained repository artifacts
plus the candidate would exceed the conservative 450,000,000-byte pool ceiling.
It uploads and proves the artifact belonging to the current workflow run before
deleting only superseded artifacts whose names exactly match the AC release
contract. An admission, upload, or proof failure therefore leaves the previous
transport artifact intact. The new transport artifact expires after one day;
the checksum-identical copy retained on the VPS is the rollback transport source.
GitHub currently does not bill
Container registry image storage or bandwidth, but this assumption must be
rechecked if GitHub announces a policy change.

The VPS never runs `git pull`, `pnpm`, `uv sync`, or a Docker build. The trusted
operator downloads the exact workflow artifact and creates a Git archive from
the exact commit:

```bash
release_sha="$(git rev-parse HEAD)"
git archive --format=tar --output="ac-application-${release_sha}.tar" \
  "$release_sha" -- infra/application
sha256sum "ac-application-${release_sha}.tar"
```

For routine staging releases, the trusted Windows controller performs that
exact flow plus artifact/CI binding, transfer, installation, and the compact
public security smoke in one idempotent command:

```powershell
pwsh -NoProfile -File .\scripts\Deploy-Staging.ps1 -ReleaseSha <full-reviewed-commit>
```

The controller requires PowerShell 7.4 or newer so native binary artifact
downloads remain byte-exact. Its random local stage is immediately reduced to
the current operating-system identity and the verified ZIP remains exclusively
open from digest calculation through extraction.

If staging already runs that exact commit, the command downloads and mutates
nothing; it only re-proves the exact release path and checksums, running image
identities (including the pinned PostgreSQL image), all five service states,
learner/API route identities, protected Admin ingress on the reviewed
`restless-cherry-c46f.cloudflareaccess.com` tenant, disabled public API docs,
and the unchanged WordPress apex/`www`.
The Google OAuth start proof runs only after a real deployment because issuing
an authorization transaction is intentionally stateful. A new deployment uses
a private fresh local and remote stage, validates the GitHub artifact ZIP
against the API's SHA-256 before inspecting its own checksum manifest, creates
the Git archive fresh from the exact commit, and removes both stages. The
command never targets production, accepts no secret values, and does not
release external side effects.

After the archive and downloaded image bundle are transferred to the VPS, run
the installer from the verified archive. The invocation is permitted only after
action-time approval naming the target environment, exact commit, backup,
migration, service reconciliation, edge reload/cutover, and rollback:

```bash
sudo AC_TARGET_ENVIRONMENT=staging \
  AC_RELEASE_ID=<full-reviewed-commit> \
  AC_RELEASE_ARCHIVE=/absolute/path/ac-application-<commit>.tar \
  AC_RELEASE_ARCHIVE_SHA256=<archive-sha256> \
  AC_IMAGE_BUNDLE_DIR=/absolute/path/ac-application-<commit> \
  /absolute/path/install-application-release.sh
```

The installer verifies the Git archive and image bundle, preserves the bundle
under `/srv/authority-closers/application/artifacts/<commit>`, and loads only
exact OCI manifest IDs. The workflow separately proves that every transport
manifest references the reviewed image config and records registry provenance;
the runtime IDs use the transport manifests imported by the foundation's
containerd image store. Before the pre-migration PostgreSQL custom-format backup, it
stops the live API and worker, revokes database `CONNECT` from the runtime and
migrator roles, terminates any remaining sessions, and proves the writer count
is zero. Only the migrator regains access for the forward migration; the
runtime role regains access only after migration succeeds. The installer then
starts the hardened services with provider effects held, proves the loopback
Caddy route identity, and atomically advances `current-<environment>`.

A catchable command failure or `HUP`/`INT`/`TERM` stops the candidate and fences
database writers again before restoring the backup. It reopens runtime access,
restores the previous release link, and restarts the previous services only
after the restore succeeds. A failed restore or access grant remains fenced and
does not restart an application against an uncertain database. `SIGKILL`,
kernel failure, and abrupt host power loss are outside shell-trap rollback; keep
external effects held and perform the documented restore/reconciliation check
before treating an interrupted deployment as committed. Deployment evidence
contains no secret values.

Alembic revisions are forward-only by project policy. Release rollback never
uses `alembic downgrade`; it restores the immutable previous application
artifact together with the installer-created pre-migration database backup,
then runs the documented reconciliation proof before side effects are released.

Staging is promoted by invoking the installer for production with the same
source archive and the same `release-images.env`; images are never rebuilt
between environments. Production still requires a separate action-time
approval. Admin ingress must be protected by Cloudflare Access before either
admin hostname is activated.

Google OAuth is mandatory for every activated staging and production release.
`AC_GOOGLE_OAUTH_CLIENT_ID` and `AC_GOOGLE_OAUTH_CLIENT_SECRET` must both be
provided from Infisical. Before image loading or any Compose command, the
installer clears ambient values and rejects a missing, empty, whitespace-only,
or partial pair without printing either value. Compose, settings validation,
and application composition provide additional fail-closed checks. Deployment
composition constructs the Google adapter only from validated settings and
rejects disabled or custom injected providers. The Google web client must
register both same-surface callbacks:

- `https://app.authorityclosers.com/v1/auth/google/callback`
- `https://admin.authorityclosers.com/v1/auth/google/callback`

Staging uses the equivalent callbacks on `staging.authorityclosers.com` and
`admin-staging.authorityclosers.com`. The preflight proves configuration
presence only; credential rotation and a real Google login/callback remain
deployment-time operational evidence. Keep `AC_EMAIL_PROVIDER=fake` and
`AC_EXTERNAL_SIDE_EFFECTS_HOLD=true` until a separately reviewed provider
activation gate is approved.

The provider port reads only the prefixed `AC_RESEND_API_KEY` and reviewed
`AC_RESEND_FROM`; both are required when the profile selects `resend`. Compose
binds the provider selector, credential, and sender only to the worker. The API
and one-shot migrator receive none of those variables and therefore retain the
application's fail-safe fake-provider default without access to the Resend
credential. The worker renders only the versioned verification, recovery, and
enrollment service templates and forwards its durable idempotency key.
Arbitrary campaign content is outside this release.

Learner registration also requires an exact `AC_PUBLIC_LEARNER_TENANT_ID` and
`AC_LEARNER_CONSENT_VERSION`. The tenant must already exist and be active.
Registration can create only an active learner membership for a verified
person; it never creates a tenant, changes a role, reactivates an inactive
membership, or provisions an admin-surface login.

Global verification/reset delivery recovery additionally requires
`AC_OPERATIONS_TENANT_ID`, pointing at an existing operations-control tenant.
Only an owner who has selected that exact tenant receives the global
job-retry/recovery permissions. This keeps tenantless identity email out of
ordinary tenant administration while retaining an attributable, idempotent
audit path.
