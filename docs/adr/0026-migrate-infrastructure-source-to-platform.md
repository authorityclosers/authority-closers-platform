# ADR-026: Migrate deployable infrastructure into the platform repository

- Status: Accepted
- Date: 2026-08-30

## Context

The live VPS was bootstrapped from the historical `authority-closers-infrastructure` repository. The approved source hierarchy places deployable configuration in the platform repository, and the live host currently contains operational files absent from the historical immutable release.

## Decision

Snapshot the historical repository's current secret-free working tree into `infra/vps-foundation`, record provenance, close reproducibility gaps here, and publish the next immutable VPS release from this repository. Preserve the historical repository until migration evidence and rollback references are complete; do not delete its history.

## Consequences

- Platform code and the deployable foundation share one review/release control plane.
- Existing live state must be reconciled before product deployment.
- The historical repository becomes a preserved migration source rather than an active authority after cutover.
