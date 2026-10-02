# Migration 20261002_0065: sensitive-segment marks and backup parity

Source pin: `8e3fe3ef` (latest main at task start, 2 Oct 2026). AUT-520 implements
step T1 of the AUT-519 plan (ETH-03 containment); ADR 0051 records D1–D7.
Reference-only: no call content appears in code, tests, fixtures or this note.

## Change

Migration `20261002_0065` follows `20261001_0064`. It creates
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
`20261002_0065` as `ac-postgres-parity-v39`: the 0064 inventory (contract v38)
plus `conversation_sensitive_segment_marks`. Earlier contracts and inventories
are unchanged; unknown heads stay fail-closed. The model registry test lists the
new table, and the release-engine tests accept a bundle at the new head only once
the foundation backup tool knows it.

## Local verification (fictional data, 2 Oct 2026)

- `tests/database/test_sensitive_segment_marks.py` plus the current-head
  capability check in `tests/database/test_capability_grants.py`, on the lane
  PostgreSQL test server (disposable schema upgraded through the real
  migration): **23 passed**. Direct SQL `UPDATE` and `DELETE` are refused with
  `conversation commands are append-only`; `reason_ref` values outside the
  pattern are refused; the head constraint carries the new capability.
- `tests/unit/http/test_platform_sensitive_segments.py` (SQLite, real identity
  and grants): **9 passed**. 401 without a session; 403 without the capability
  for reads and writes; mark, re-mark (no-op), release, mark again leaves three
  rows with one audit event each naming the operator and reason; same-key
  replay writes nothing; 404/409/422 cases; a duplicate upload sharing the
  `transcript_revision` sees the marks; no response or log line carries the
  fixture sentinel.
- `tests/unit/http/test_platform_access.py`, `tests/database/test_model_registry.py`
  and `tests/database/test_capability_grants.py` with the above: **112 passed**.
- `tests/infra/test_capability_backup_parity.py` and `tests/infra/test_ac_release.py`:
  **89 passed, 2731 skipped** (the root-gated metadata and restore-parity cases
  skip for a non-root local account, as before).
- `ruff format --check` and `ruff check` on `packages/python`, `tests`, the
  migration and the three parity scripts: clean. `mypy packages/python`: clean
  (366 files).

This is code-level parity evidence only. No host backup, live restore drill or
migration rehearsal pair was run. The shared sandbox database already carries
the api lane's unmerged `20261002_0065_plans` revision, so this migration was
not applied there; the reviewer settles the revision order (see the PR).
