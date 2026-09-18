# Sales Xray 0030 recovery compatibility

This bounded follow-up starts from integrated source
`0bf1c97950afdefab8f234870f10445c5167008a`. It extends the immutable logical-backup,
offsite restore-proof and application restore-drill controllers to the exact
`20260913_0030` migration. It does not activate Sales Xray intake, inference,
providers or review import, and does not change a migration or application model.

The new `ac-postgres-parity-v10` contract retains every table in the 0029/v9
contract and adds the thirteen tables created by the frozen 0030 migration:

```text
conversation_budget_accounts
conversation_review_cursors
conversation_minute_accounts
conversation_permissions
conversation_recordings
conversation_checkpoints
conversation_commands
conversation_quotes
conversation_runs
conversation_reviews
conversation_quote_acceptances
conversation_provider_configurations
conversation_report_drafts
```

Historical migration-to-contract mappings remain intact. The rehearsal accepts
the separately named 0027→0029 and 0029→0030 transitions. The original transition
retains its 0028 profile/person derivation checks; the 0030 transition preserves
all prior table counts and requires each newly created table to be empty. It does
not infer transitions from revision ordering. Future 0031 compatibility requires
a separate frozen migration and reviewed contract.

## Verification

The real PostgreSQL regression ran on the existing source-owned PostgreSQL 18
test runtime at loopback port 55432. The runner created one fresh database with
the required `ac_migration_rehearsal_` prefix; each case used its own generated
schema. Neither an API database URL nor a production database was used. The
test database was removed after completion.

`tests/integration/test_migration_rehearsal_postgresql.py`: **2 passed in 43.49s**.
The existing populated 0027→0029 case remains. The new case reaches 0029 with
two people, three memberships, three legacy profiles, two global community
profiles, three leaderboard preferences and three immutable app-update receipts.
It compares the complete contents of every existing table before and after the
0030 migration, checks the exact migration head, and requires all thirteen new
tables to start empty.

Receipts are outside Git under
`D:/Projects/authority-closers-release-transfer/2026-09-11-recovery/0030-recovery-receipts/`:
`postgresql-0027-0029-0030.xml` and `postgresql-0027-0029-0030.log`.

The final combined controller fixture run passed **529 tests in 24.25s**, with
the Docker input-readability case and explicitly opt-in live restore case
deliberately deselected. This total includes the 466 parity cases; it must not be
added to that earlier overlapping subset. The final receipt is
`parity-and-rehearsal-final.xml` in the same external directory.

Coverage includes exact source/target image and migration bindings, historical
contract preservation, migration-derived table inventory, populated source count
preservation, empty new tables, incomplete/extra/invalid count rejection,
unsupported migration pairs and 0031 rejection, and the existing isolated
network/role/resource and recovery-hold checks. The separate populated PostgreSQL
cases above validate real DDL and full existing row contents; fixture passes do
not imply an executed Docker restore.

Ruff lint and formatting, evidence Prettier formatting and `git diff --check`
passed. Independent read-through of the controller handoff found no additional
actionable issue. Changes are confined to the three controllers, the two infra
fixture modules, the populated PostgreSQL regression module and this evidence.

## Deployment limits

No VPS deployment, application selector change, provider call or operational SQL
recovery occurred. Backup retention, compression, concurrency, the remote storage
ceiling and the no-bypass policy are unchanged. This source checkpoint does not
attest a Docker image, a production dump restore or live rollback. Those remain
exact-artifact release gates; the installed foundation controllers must also be
updated through their reviewed immutable deployment path before relying on the
new parity contract.
