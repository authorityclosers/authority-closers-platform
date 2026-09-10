# Staging off-site restore acceptance — 2026-09-10

Result: **passed** for staging release `74631e0dd94a1d54a2e2b88bc925e47e0e0c7029`, migration `20260910_0027`. This supersedes the outstanding restore-proof status for this exact release; it does not erase historical backup failures or establish production readiness.

Root verified the three installed canonical restore helpers against the reviewed source before starting the single `ac-restic-postgres-restore-proof@staging.service` invocation at 03:13:08 UTC. It waited for the existing canonical backup, which completed successfully at 03:14:17 UTC. No duplicate backup was started.

The job retrieved the tagged off-site snapshot captured at 03:10:29 UTC, validated the logical dump and metadata hashes against the current release, and restored into a disposable, internal-network-only PostgreSQL target. The live database was not restored or edited. Provider calls and worker processing remained blocked in the recovered target.

Read-back evidence:

- Directory: `/srv/authority-closers/recovery-evidence/postgres-logical/staging-20260910T031446Z-80a0f8a1b1b4`.
- `off-site-restore-proof.json`: result `passed`, exact release above, snapshot `4b6f5b5ff2a1060442627ad6da18a0a06f8d2ea65bc7fff295e39584057c58bb`.
- `restore-drill-7a72b3260115.json`: operation and objective gates passed; parity contract `ac-postgres-parity-v7`, 55 canonical tables checked, exact migration head, invariant violations zero.
- Backup age 282.278 seconds against a 900-second target; isolated restore/verification 9.738 seconds against a 3,600-second target. These are this drill's measurements, not a production recovery guarantee.
- Recovery marker held; worker `run_once` rejected; provider calls zero; no external connections or published ports; no reconciliation requested.
- Completed at 03:15:15.779365 UTC; cleanup `completed`. Independent Docker container, network and volume queries for the exact run label returned no resources.
- Independent read-back still resolved `current-staging` to exact `74631e0dd94a1d54a2e2b88bc925e47e0e0c7029`. No application deployment, restart, production configuration, DNS or WordPress change was made by this verification.

Production's missing managed application/identity configuration and its own acceptance remain separate gates. Arcade code is present in this staging artifact but its immutable release policy is disabled; a reviewed new artifact is required to enable the approved academy pilot.
