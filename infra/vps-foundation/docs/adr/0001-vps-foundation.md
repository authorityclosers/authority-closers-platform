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
- Public SSH remains temporarily available with key-only authentication until a private management plane is enrolled.
- External secret management, off-host backup key escrow, and production DNS cutover remain separate gates.
