# Authority Closers Infrastructure Foundation

This repository defines the reproducible baseline for the Authority Closers KVM4 VPS.
The VPS is a deployment target, not a source-code workstation.

- Operator access: `ssh ac`
- Public foundation health: `https://infra.dipakvishwakarma.com/healthz`
- Operations runbook: `runbooks/OPERATIONS.md`

## Invariants

- Production workloads are OCI images promoted by immutable digest.
- Product source is never edited on the server.
- Public HTTP ingress uses a named Cloudflare Tunnel.
- Application routes are selected independently for staging and production by
  root-owned symlinks under `/srv/authority-closers/application/edge-routes`.
  Their route-only targets under `edge-route-releases` are mode `0444` copies
  re-compared to checksum-verified immutable foundation or application
  releases before selection. Caddy mounts only the selector and projection
  directories read-only, so links resolve inside its unprivileged container
  without exposing release trees, application state, or secrets and without
  making mutable VPS state authoritative.
- The bootstrap route keeps new production app hosts and not-yet-released
  Learner/Coach staging hosts on explicit no-store 503 maintenance responses.
  Existing staging Admin/API and legacy Learner routes remain selected until
  the staging application transaction changes only its environment selector.
- Databases, queues, admin ports, and Docker APIs are never published to the public Internet.
- The Docker group remains empty because membership is root-equivalent.
- Secrets are not committed here or placed in images.
- Persistent state lives under `/srv/authority-closers/volumes` and is backed up off-host.
- Logs are bounded and operational telemetry uses OpenTelemetry-compatible interfaces.
- The current `dipakvishwakarma.com` apex remains on the old VPS until an explicit migration gate passes.
- R2 stays on Standard storage inside an 8 GiB, 700k Class A, and 7M Class B monthly operating envelope; every backup runs the usage guard before writing and fails closed when the envelope cannot be proven safe.

## Repository layout

- `scripts/` - idempotent bootstrap and validation entry points.
- `config/` - reviewed host configuration installed by the bootstrap.
- `compose/foundation/` - internal reverse proxy and telemetry boundary.
- `ansible/` - controller entry point for repeatable provisioning.
- `runbooks/` - operations and recovery procedures.
- `docs/adr/` - consequential architecture decisions.
- `config/release/` - committed image digests, tool versions/checksums, and the complete host install manifest.

## Bootstrap gates

1. Build one Git archive from the full reviewed 40-character commit and record its SHA-256. Every phase must execute from that checksum-verified archive; the bootstrap refuses a payload that differs by even one tracked or extra file.
2. Run the archive-extracted `bootstrap-host.sh access /path/to/admin.pub` with `AC_RELEASE_ID`, `AC_RELEASE_ARCHIVE`, and `AC_RELEASE_ARCHIVE_SHA256`.
3. Verify a fresh public key-only SSH session as the named administrator.
4. Run the same archive-extracted `bootstrap-host.sh baseline`. This is a separately versioned host baseline with top-level pins plus a checksum-bound complete 555-package dependency graph; installation fails unless the live graph matches it exactly and later fails on any drift.
5. On a fresh host only, run `AC_ALLOW_PUBLIC_SSH_BOOTSTRAP=1 bootstrap-host.sh harden` from the same archive to keep TCP/22 temporarily available.
6. Verify SSH key-only access and firewall state.
7. Run `bootstrap-host.sh runtime` from the same archive. This installs the exact-commit immutable release, release-scoped toolchain, every managed script/unit, and the digest-pinned Compose foundation.
8. Provision the root-owned Cloudflare Tunnel token, then run `bootstrap-host.sh activate cloudflared` from the same archive.
9. Prove a second, fresh Cloudflare Access SSH session.
10. Run `AC_CLOUDFLARE_SSH_VERIFIED=YES bootstrap-host.sh lockdown` from the retained session and same archive, then prove another Access session while confirming UFW denies IPv4 and IPv6 TCP/22.
11. Run `AC_PUBLIC_HEALTH_URL=https://infra.dipakvishwakarma.com/healthz /usr/local/sbin/ac-validate-foundation` as root.
12. After the Infisical bootstrap, R2 repository, first backup, and restore evidence exist, run `bootstrap-host.sh activate r2-jobs` from the same archive. Activation fails closed unless current usage and restore checks pass.
13. After a healthy current staging application release exists, run `bootstrap-host.sh activate postgres-backup` from the same archive. This separate gate verifies exact units, current usage plus the logical storage projection, a no-write dry-run, and capture/`pg_restore --list` evidence before enabling the five-minute timer.

CI proves that working-tree mutations cannot enter an exact-commit release, rejects a mutated controller verifier and unsafe archive path, failure-injects host installation both before and after symlink activation to prove automatic rollback, smoke-tests the installer against a clean synthetic filesystem root, and requires every `ac-*` operational script and systemd unit to appear in the explicit install manifest. Provider-dependent activation remains a separate, named gate so a clean host cannot silently start an unconfigured external writer.

Never skip the fresh-session checks between gates.
