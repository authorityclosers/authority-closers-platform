# Guest processing restore parity

The backup writer, off-site restore verifier, and isolated restore drill now
share the reviewed `ac-postgres-parity-v17` contract for migration
`20260914_0037`. It extends the `20260914_0036` inventory with
`conversation_processing_principals`, `conversation_processing_leases`, and
`conversation_guest_submissions`. Earlier migration heads and their table
inventories remain explicit compatibility contracts.

The exact isolated rehearsal is `20260914_0036` to `20260914_0037`. It
preserves every source row count and requires all three new tables to be empty
after the forward migration. The restore runbook requires the prior-head
backup and source image to attest `0036`, and the candidate image and checked-in
workspace to attest `0037`.

## Validation

- Focused restore-drill tests: **76 passed, 2 expected skips**.
- Backup, restore-proof, and parity contract tests: **885 passed**.
- Backup/restore-drill/proof focused suite: **154 passed, 9 expected skips**.
- Fresh disposable loopback PostgreSQL rehearsal: source head `0036`, target
  head `0037`, 111 source tables and row counts preserved, 114 target tables,
  three new tables empty, actor-binding columns/checks and immutable ownership
  triggers present, zero provider calls.

Receipt: `D:/AC-authority-closers-release-audit/sales-restore-0036-0037-helpers-20260914.json`

SHA-256:
`991F64F3102DEE0A633BC85D33C4F7090CC1A32A61C20ABF87CDB706816B5C3D`

The receipt contains no database URL or credential material. No production
database, backup, deployment, or provider endpoint was accessed.
