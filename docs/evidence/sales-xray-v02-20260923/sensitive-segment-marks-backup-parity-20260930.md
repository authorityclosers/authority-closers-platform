# Migration 20261002_0067: sensitive-segment marks and backup parity

Source pin: `dd5106d9` (main after PR #203 merged, 2 Oct 2026; first opened at `8e3fe3ef` as 0065, renumbered to 0066 after #199 and to 0067 after #203 on CTO review). AUT-520 implements
step T1 of the AUT-519 plan (ETH-03 containment); ADR 0051 records D1–D7.
Reference-only: no call content appears in code, tests, fixtures or this note.

## Change

Migration `20261002_0067` follows `20261002_0066` (`platform_billing_manage`). Both migrations drop and recreate the two `capability_grants` checks, so 0067's checks list `platform_billing_manage` and `platform_content_safety_manage`, as do `CapabilityGrant`, `PLATFORM_CAPABILITIES` and the `PlatformPermission` literal; a PostgreSQL test proves both platform grants insert at the head. It creates
`conversation_sensitive_segment_marks` (one row per mark or release, IDs only),
with database checks for `category`, `action`, `source`, the
`release ⇒ supersedes_mark_id` shape, the `reason_ref` length bounds and, on
PostgreSQL, the `reason_ref` pattern; unique `supersedes_mark_id` and
`audit_event_id`; indexes on `(tenant_id, recording_id)` and
`(transcript_revision)`; and a `BEFORE UPDATE OR DELETE` trigger that reuses
`prevent_conversation_command_mutation()` from 0030. It also adds
`platform_content_safety_manage` to both `capability_grants` checks (the
0054/0060 pattern). `downgrade()` raises.

All three independently packaged recovery helpers (`ac-postgres-backup.py`,
`ac-restic-postgres-restore-proof.py`, `restore-drill.py`) register head
`20261002_0067` as `ac-postgres-parity-v40`: the 0065/0066 inventory (contract v39,
120 tables) plus `conversation_sensitive_segment_marks`, 121 tables. Earlier contracts and inventories
are unchanged; unknown heads stay fail-closed. The model registry test lists the
new table, and the release-engine tests accept a bundle at the new head only once
the foundation backup tool knows it.

## Local verification (fictional data, 2 Oct 2026, head 0067)

- CI's drift gate, `alembic upgrade head && alembic check`, in a disposable
  schema on the lane PostgreSQL test database: upgrades `0065 -> 0066 -> 0067`,
  "No new upgrade operations detected", `alembic current` = `20261002_0067 (head)`.
  The first PR failed this gate: the PostgreSQL-only `reason_ref` pattern check
  had no model counterpart, and the transcript-revision check name exceeded 63
  characters. The model now compiles the pattern per dialect and the check is
  named `revision_bound`.
- `tests/database/test_sensitive_segment_marks.py` (SQLite plus a disposable
  PostgreSQL schema upgraded through the real migration), `tests/unit/http/
  test_platform_sensitive_segments.py`, `tests/database/test_model_registry.py`,
  `tests/database/test_capability_grants.py`, `tests/unit/http/test_platform_access.py`,
  `tests/unit/plans`, `tests/infra/test_capability_backup_parity.py` and
  `tests/infra/test_ac_release.py`: **228 passed, 2837 skipped** (the root-gated
  metadata and restore-parity cases skip for a non-root local account, as before).
  Direct SQL `UPDATE` and `DELETE` are refused with `conversation commands are
  append-only`; `reason_ref` values outside the pattern are refused; 401 without
  a session and 403 without the capability for reads and writes; mark, re-mark
  (no-op), release, mark again leaves three rows with one audit event each; a
  duplicate upload sharing the `transcript_revision` sees the marks; no response
  or log line carries the fixture sentinel.
- `ruff format --check` and `ruff check` on every changed Python file: clean.
  `mypy packages/python`: clean (368 files).

This is code-level parity evidence only. No host backup, live restore drill or
migration rehearsal pair was run. The shared sandbox database was not
migrated by this task; the migration ran only in disposable schemas on the lane
test database (upgrade head, `alembic check` and the trigger proof).
