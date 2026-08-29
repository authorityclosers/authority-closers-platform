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

## Bootstrap gates

1. `bootstrap-host.sh access /path/to/admin.pub`
2. Verify a fresh SSH session as the named administrator.
3. `bootstrap-host.sh harden`
4. Verify SSH key-only access and firewall state.
5. `bootstrap-host.sh runtime`
6. Pin foundation images by digest and start the Compose project.
7. Install the named Cloudflare Tunnel and validate the external hostname.
8. Run `AC_PUBLIC_HEALTH_URL=https://infra.dipakvishwakarma.com/healthz scripts/validate-foundation.sh` as root.
9. Before enabling any new R2 writer, run `scripts/r2-usage-guard.sh` with a metrics-capable API token and complete a reversible `scripts/r2-probe.sh` test using bucket-scoped credentials.

Never skip the fresh-session checks between gates.
