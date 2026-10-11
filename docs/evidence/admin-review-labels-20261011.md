# Call review labels and the gold set — AUT-1798 (Strike G, phase 2)

Reviewers (AC staff with Admin's call review access) can now judge each call:
verdicts per section, notes, Dipak's gold label, training/test data marks and
the review state, all stored append-only.

## Storage

- Migration `20261011_0083` adds one table, `conversation_review_labels`.
  Purely additive. One row is one reviewer statement; a later statement
  supersedes an earlier one as a new row. The existing
  `prevent_conversation_command_mutation` trigger refuses UPDATE and DELETE.
  Each row names the audit event that recorded it.
- Writes are idempotent per actor and Idempotency-Key; the same key with a
  different body is refused (409).
- Backup and restore: row-count parity contract `ac-postgres-parity-v54` adds
  the table to the backup, restic restore proof and restore drill consumers
  (otherwise backups refuse the new migration head).

## Access

The same admission as the call review console: Admin host, operations
workspace and the Sales Xray control accounts. Nothing is exposed outside
Admin, and the gold-set view is labelled internal and not an official score
(AC-SVAL gates, AGENTS.md).

## Verification

- Unit tests for label states, values, sections and admission; route tests;
  PostgreSQL cases for append, supersede, idempotency, trigger, audit, queue
  review states and the gold view (CI).
- Infra: the new parity contract is asserted in all three consumers.
- admin-web: label data, the Review panel's keyboard and failure states, Home
  review tiles, queue filters with review tabs; typecheck, ESLint and Prettier.
- One migration head after `20261011_0082`.
