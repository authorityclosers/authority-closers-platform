# Guest acquisition migration and release recovery

Application CI run `34777711272` stopped with 15 failures, 5,211 passes and 855
skips. The new `20260914_0036` guest acquisition migration was registered by the
application but missing from the independent backup/restore parity catalogues.
This prevented the restore controller from accepting the candidate migration
head. The registry expectation also omitted its four tables, and its downgrade
error did not use the existing forward-only marker.

The backup writer, restore verifier and isolated restore drill now share the
explicit `ac-postgres-parity-v16` contract: all 85 prior representative tables,
plus visitors, visitor claims, acquisition usage and acquisition settlements.
Historical contracts retain their original inventories. The exact 0035-to-0036
rehearsal requires unchanged existing row counts and empty new tables. The
previously registered 0034-to-0035 invitation rehearsal now has its missing
transition check too. Neither transition infers or creates account/usage rows.

The new tests reject missing or unexpectedly populated acquisition/invitation
tables and loss of existing person rows. The expanded parity suite also checks
all three packaged helpers against the actual migration's table declarations
and requires full metadata for populated backups.

Local verification: 897 tests passed and two Docker-dependent tests skipped in
53.10 seconds across restore drills, backup parity and model registry. Scoped
Ruff and formatting passed. Receipt:
`D:/AC-authority-closers-release-audit/acquisition-parity-0036.xml`.
The Linux Docker/root restore check remains required in the combined CI rerun.
No deployment or production backup/restore was performed by these tests.
