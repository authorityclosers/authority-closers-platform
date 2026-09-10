# Practice, Focus and authoring recovery parity — local contract evidence

Date: 2026-09-08. Scope: source changes and local automated tests only.

The independently packaged [backup writer](../../infra/vps-foundation/scripts/ac-postgres-backup.py), [off-site proof controller](../../infra/vps-foundation/scripts/ac-restic-postgres-restore-proof.py), and [application restore controller](../../infra/application/scripts/restore-drill.py) now use matching, explicit migration contracts:

| Reviewed migration | Contract | Required representative tables |
| --- | --- | ---: |
| Existing explicit legacy catalogue through `20260904_0018` | Unchanged V1 metadata | 39 |
| `20260907_0019` | `ac-postgres-parity-v2` | 41 |
| `20260908_0020` | `ac-postgres-parity-v3` | 50 |
| `20260908_0021` | `ac-postgres-parity-v4` | 52 |
| `20260908_0022` | `ac-postgres-parity-v5` | 53 |

The additions cover all nine practice tables (including pinned definitions, responses, acknowledgments, reward claims and ledger entries), both Focus tables, and immutable Studio authoring commands. The source query binds counts and migration head to the same exported dump snapshot. Both proof controllers require the matching metadata contract, exact head and complete row-count equality. Unknown future heads fail closed; table presence never selects a fallback contract.

Coach image provenance is accepted only as a complete image/transport/registry triplet with the same existing strict digest validation. Historical three-image releases remain compatible. Inherited Coach image, app-origin and edge-alias environment values cannot override the verified backup profile.

Validation: **256 passed, 9 skipped** in 19.94 seconds across `test_capability_backup_parity.py`, `test_postgres_backup.py`, `test_postgres_restore_proof.py`, and `test_restore_drill.py`. This includes exact historical-controller V1 compatibility, cross-head rejection, migration-AST table inventory, each new table's missing/lost/boolean count rejection, and Coach inventory/scrub regressions. Scoped Ruff and `git diff --check` passed. The existing Linux root-test gate already includes the expanded parity file.

Skips: seven POSIX-specific checks, one unavailable-Docker check and one explicitly gated restore integration. No live backup, database restore, migration, VPS deployment or Linux CI execution was performed. Row-count parity does not independently prove row-content equality or replace database invariant/audit-chain validation and a real restore rehearsal. Independent review remains with the parent before release activation.
