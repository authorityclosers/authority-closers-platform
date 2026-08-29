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

1. `bootstrap-host.sh access /path/to/admin.pub`
2. Verify a fresh public key-only SSH session as the named administrator.
3. On a fresh host only, run `AC_ALLOW_PUBLIC_SSH_BOOTSTRAP=1 bootstrap-host.sh harden` to keep TCP/22 temporarily available.
4. Verify SSH key-only access and firewall state.
5. Set `AC_RELEASE_ID=foundation-<reviewed-git-sha>` and run `bootstrap-host.sh runtime`. This installs the full immutable release, every managed script/unit, and the committed digest-pinned Compose foundation.
6. Provision the root-owned Cloudflare Tunnel token, then run `bootstrap-host.sh activate cloudflared`.
7. Prove a second, fresh Cloudflare Access SSH session.
8. Run `AC_CLOUDFLARE_SSH_VERIFIED=YES bootstrap-host.sh lockdown` from the retained session, then prove another Access session while confirming UFW denies IPv4 and IPv6 TCP/22.
9. Run `AC_PUBLIC_HEALTH_URL=https://infra.dipakvishwakarma.com/healthz /usr/local/sbin/ac-validate-foundation` as root.
10. After the Infisical bootstrap, R2 repository, first backup, and restore evidence exist, run `bootstrap-host.sh activate r2-jobs`. Activation fails closed unless current usage and restore checks pass.

CI smoke-tests the installer against a clean synthetic filesystem root and requires every `ac-*` operational script and systemd unit to appear in the explicit install manifest. Provider-dependent activation remains a separate, named gate so a clean host cannot silently start an unconfigured external writer.

Never skip the fresh-session checks between gates.
