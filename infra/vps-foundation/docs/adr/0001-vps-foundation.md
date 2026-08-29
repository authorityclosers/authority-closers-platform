# ADR 0001: Disposable VPS foundation with tunneled ingress

- Status: Accepted
- Date: 2026-08-26

## Decision

Use the KVM4 VPS as a portable deployment target. Public HTTP ingress is delivered through a named Cloudflare Tunnel to a loopback-only Caddy listener. Docker workloads use isolated user-defined networks and image digests. Authority Closers state/configuration follows the `/srv/authority-closers/` convention. PostgreSQL, R2/S3-compatible storage, Resend, and telemetry remain behind explicit application adapters.

## Consequences

- No public ports 80/443 are required on the VPS.
- Traefik and on-host public certificate automation are not required for the initial topology.
- Cloudflare is an edge dependency, not product business logic.
- The production apex can remain on the old VPS while a subdomain validates the new foundation.
- Public TCP/22 is denied after independently verified Cloudflare Access SSH enrollment. A public key-only rule is permitted only as an explicit, temporary fresh-host bootstrap exception.
- Infisical secret management and encrypted off-host backup/restore are active. Production application DNS cutover remains a separate gate.
- Host packages are promoted as a separately versioned, exact-package OS baseline. Foundation releases contain no mutable package upgrade step.
- A foundation release is materialized only from a checksum-verified Git archive whose embedded full commit matches the release ID; release-scoped operational binaries are reconciled during both promotion and rollback.
