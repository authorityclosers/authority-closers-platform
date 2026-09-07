# Capability backup parity compatibility — 2026-09-07

## Result and boundary

Local recovery candidate implemented and independently reviewed by the parent orchestrator. This is not evidence of a deployed foundation, a live capability grant, or a successful live 0019 restore. No remote backup, deployment, metadata edit, identity grant, or commit was performed by this implementation task.

The three separately packaged recovery helpers now select an explicit reviewed table-count contract using the sealed application migration head. Unknown heads fail closed. The historical 39-table contract remains unchanged; the 0019 contract requires both immutable capability history tables, for 41 tables total.

## Compatibility contract

- Historical heads explicitly listed from checked-in revisions: 20260830_0006 through 20260830_0011; 20260901_0012; 20260902_0013 and 0014; 20260903_0015 and 0016; 20260904_0017 and 0018.
- Historical metadata retains its exact original V1 field shape. New fields are not added to old captures, so an existing immutable controller is not forced to accept unfamiliar metadata.
- Head 20260907_0019 requires ac-postgres-parity-v2, the matching migration_head metadata field, and all 41 named row counts. Missing, partial, mismatched, boolean, negative, or changed capability counts are rejected.
- The capture helper queries the actual migration head and all selected row counts from the same exported repeatable-read snapshot used for the dump. A release/snapshot migration-head mismatch is rejected.
- The application controller binds source/release identity, metadata, restored migration head, required tables, and 0019 source/restored counts. The offsite proof helper separately verifies the same selected table set, exact migration evidence, and count equality.
- Capability table presence does not select the contract; lexical migration comparisons and unknown-head fallback are not used.

## Validation

Command: uv run pytest tests/infra/test_capability_backup_parity.py tests/infra/test_postgres_backup.py tests/infra/test_postgres_restore_proof.py tests/infra/test_restore_drill.py -q

Result: **132 passed, 9 skipped in 8.30 seconds** on Windows. Ruff check and format check passed for all three helpers and all four test modules. Git Bash syntax validation of tests/infra/run.sh and Git diff whitespace validation passed.

The new compatibility module directly loads the tracked historical controller from commit 35c658bd028b4fc3a7c048ab72dae700cd7682d6 in memory and invokes its metadata validator against newly generated V1 metadata. This test executed and passed locally; it does not merely compare the current validator with itself. In a shallow checkout without that exact historical Git object, this one historical execution test explicitly skips rather than substituting a different controller. Other current-contract and exact-field-shape tests remain independent of that object.

All three head catalogues and table tuples are checked for equality. Every explicitly supported head is also checked against actual checked-in migration revision identifiers. Tests cover old/new contract mismatch, unknown heads, snapshot identity mismatch, missing/duplicate snapshot head, partial query output, missing capability tables/counts, restored-head mismatch, and changed grant/revocation records through count differences.

The nine local skips are four POSIX Bash checks, two POSIX file-lock checks, one POSIX no-follow check, one unavailable Docker-daemon test, and one explicitly opt-in real restore drill. They are not claimed as local passes. Row-count parity remains a row-count proof, not a content checksum of individual database rows.

## CI wiring and review correction

Review identified that the new root-owned metadata tests would otherwise all skip under non-root application CI. Both root and sudo branches of tests/infra/run.sh now invoke test_capability_backup_parity.py alongside test_postgres_restore_proof.py. The shell script retains LF-only bytes. Linux root-owned execution of this newly wired test module is pending CI and is not inferred from Windows success.

Review also caught an invalid historical test fixture workspace path: the fixture accidentally put the dump inside the declared workspace and correctly triggered the existing safety guard. The fixture now supplies the real repository path; the safety guard remains unchanged.

## Required activation sequence

1. Deliver the backward-compatible foundation helper update while the old application/controller can still use unchanged V1 metadata.
2. Deliver the reviewed application release and migration 0019.
3. Capture through the canonical version-bound workflow and run the isolated offsite restore proof for the exact 0019 release and data.
4. Require that new proof before declaring recovery coverage for populated capability grants/revocations. A historical 0018 proof cannot establish capability recovery coverage.

No live RPO/RTO result or successful 0019 recovery is claimed here. Existing unrelated files and user changes remain preserved.
