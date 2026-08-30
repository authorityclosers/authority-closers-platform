# PostgreSQL restore-drill evidence

Complete this cover sheet for the generated JSON evidence. Do not paste
credentials, DSNs containing passwords, provider payloads, email addresses,
session tokens, OAuth values, or raw job/outbox payloads.

## Identity

- Environment label: `<staging|production>`
- Drill run ID: `<run_id>`
- Operator/reviewer: `<name or team identifier>`
- Review date (UTC): `<timestamp>`
- Backup SHA-256: `<64 lowercase hex characters>`
- Backup metadata SHA-256: `<64 lowercase hex characters>`
- Selected Restic snapshot ID: `<64 lowercase hex characters>`
- Selected snapshot pair: `<one capture directory / backup.dump + metadata.json>`
- Backup release ID: `<40-character Git commit>`
- Backup capture timestamp (UTC): `<verified paired-metadata timestamp>`
- Restic/capture freshness and ordering: `<pass|fail>`
- Evidence JSON: `<relative filename>`

## Target isolation

- PostgreSQL server version: `<18.x>`
- Target database identity: `<generated name>`
- Target role identity: `<generated name>`
- Docker network: `<generated internal network>`
- Disposable state volume: `<generated volume>`
- Published host ports: `None`
- Source environment connection opened: `No`
- External provider connection opened: `No`
- Cleanup: `<completed|failed-operator-attention-required>`

## Restore and data checks

- Custom-format `pg_restore --list`: `<pass|fail>`
- Alembic migration identity: `<expected = actual>`
- Canonical tables checked: `<count>`
- Representative row counts reviewed: `<yes|no>`
- Source/restored critical-table row-count parity: `<pass|fail>`
- Invariants before hold: `<pass|fail>`
- Restore marker: `<generation/status/held counts>`
- Held pending outbox after marker: `<count; must be 0 pending>`
- Held uncertain external jobs after marker: `<count; must be 0 uncertain>`

## Side-effect fence

- Worker ready while held: `False`
- Worker `run_once()` rejected: `True`
- Recording provider calls: `0`
- Selected reconciliation requested: `<yes|no>`
- Selected job IDs: `<IDs or none>`
- Selected outbox event IDs: `<IDs or none>`
- Unselected held records remained held: `<yes|no|not applicable>`
- Same-transaction audit evidence: `<yes|no|not applicable>`

## Recovery objectives

- Observed RPO seconds: `<JSON value>`
- RPO target seconds: `900`
- RPO within target: `<true|false>`
- Observed RTO seconds: `<JSON value>`
- RTO target seconds: `3600`
- RTO within target: `<true|false>`
- Objective assessment: `<pass|fail|insufficient backup timestamp evidence>`

## Review notes

`<Record backup provenance, migration-head review, invariant exceptions, any
cleanup follow-up, and the explicit decision to keep or supersede the
recovery evidence.>`
