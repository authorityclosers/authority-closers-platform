# AUT-1676: minute journal backup and validation contracts

The 0079 append-only journal is part of the exact v50 backup/restore parity
inventory in all three consumers. No backup, restore or server change was run.
Registry and legacy-upgrade fixtures account for the new table; the legacy
0076 population uses scoped pre-journal projections only before upgrading.
The isolated metrics fixture continues to stub upstream ownership, including
the new delivery port. Exact source ownership and capture are tested separately
by the report-minute PostgreSQL suite.

Validation: 115 passed and 2 intentional integration skips in the focused
backup/restore, model, legacy-upgrade, metrics and withheld regression batch.
Five native C1-dependent cases failed in local-worker setup before reaching the
changed assertions; native decoding verification remains for CI. The terminal
run assertion now expects a failed run's recorded finish time, matching the
already committed worker behavior. A retained held-plan assertion includes the
coordinator's minute-outcome recovery marker.

This is part of the single sensitive strike PR #421, requiring CTO and CEO
review. The shared migration gate is still held by open PR #414.
