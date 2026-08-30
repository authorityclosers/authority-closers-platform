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
- PostgreSQL is reachable only on the internal data network. The owner,
  migrator, runtime, and backup credentials are distinct Infisical secrets.
- Session tokens are stored only as peppered digests; the token pepper and the
  independent OAuth-transaction signing secret are required Infisical values
  and never enter an image, repository, URL, log, or browser-readable cookie.
- Learner and admin sessions use host-only cookies: no cookie carries a
  `Domain` attribute for `authorityclosers.com`. Caddy routes `/v1/*` on
  `app.authorityclosers.com` and `admin.authorityclosers.com` to the API before
  their Next.js fallbacks, so Google callbacks return to the initiating
  surface without extending trust to the WordPress apex or the other surface.
- Google authorization state is persisted before redirect as a one-time,
  expiring database transaction. Only hashes of state, nonce, and PKCE verifier
  are durable; the HMAC-authenticated browser transaction references its UUID.
- Uvicorn does not accept forwarded proxy headers. Application authorization
  never derives a person, tenant, role, permission, or resource owner from
  caller-controlled proxy or request fields.
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
The transport artifact expires after one day to keep pooled GitHub Actions
storage inside the Free-plan allowance; the checksum-identical copy retained on
the VPS is the rollback transport source. GitHub currently does not bill
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
under `/srv/authority-closers/application/artifacts/<commit>`, loads only exact
image IDs, creates a pre-migration PostgreSQL custom-format backup, migrates,
starts the hardened services with provider effects held, proves the loopback
Caddy route identity, and atomically advances `current-<environment>`. A
catchable command failure or `HUP`/`INT`/`TERM` stops the candidate, restores
the database backup, and reconciles the previous release. `SIGKILL`, kernel
failure, and abrupt host power loss are outside shell-trap rollback; keep
external effects held and perform the documented restore/reconciliation check
before treating an interrupted deployment as committed. Deployment evidence
contains no secret values.

Staging is promoted by invoking the installer for production with the same
source archive and the same `release-images.env`; images are never rebuilt
between environments. Production still requires a separate action-time
approval. Admin ingress must be protected by Cloudflare Access before either
admin hostname is activated.

Google OAuth remains fail-closed when `AC_GOOGLE_OAUTH_CLIENT_ID` and
`AC_GOOGLE_OAUTH_CLIENT_SECRET` are absent. When enabled, both values must be
provided together from Infisical, and the Google web client must register both
same-surface callbacks:

- `https://app.authorityclosers.com/v1/auth/google/callback`
- `https://admin.authorityclosers.com/v1/auth/google/callback`

Staging uses the equivalent callbacks on `staging.authorityclosers.com` and
`admin-staging.authorityclosers.com`. Keep `AC_EMAIL_PROVIDER=fake` and
`AC_EXTERNAL_SIDE_EFFECTS_HOLD=true` until a separately reviewed provider
activation gate is approved.
