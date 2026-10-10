# AUT-1694: additive username identity schema candidate

Sensitive identity/migration change. Local source pin: `243947186621fd5e36a3920e00959e7c022bc112`, based on main `43d6eafd7c6f9c58df89903a1873ebb107c14d23` (migration `20261010_0080`). Not published or deployed.

The owner requested optional-email username accounts, one-time Admin temporary passwords and mandatory first change. Four person columns separate username possession proof, forced password change and temporary expiry from existing mailbox proof. The username index is case insensitive; normalized length, verification binding and forced-change expiry constraints are enforced. Existing identities default to no forced change. This adds no new table, account, entitlement or processing approval. Recovery is forward only.

`tests/integration/test_username_schema_postgresql.py` migrates a fresh isolated PostgreSQL schema using the provided test database. It verifies the four columns, legacy email/default behavior, duplicate refusal and verification/expiry binding constraints. It also checks the repository's additive migration classification. This is fresh-schema/default proof, not an application to existing staging or production data.

The schema case passed within the 249-check actual-tree identity/organisation suite. The final schema-only check is recorded in the Strike E NOTES.md receipt, after aligning the Boolean server default with the repository classifier's accepted SQLAlchemy vocabulary. Ruff check/format and diff checks pass.

Release is blocked: #436 holds the shared-file PR slot. Strike C owns current uncommitted edits to all three backup/restore parity consumers and is preparing `20261011_0081_recording_imports.py`. This candidate's `20261010_0081` allocation is provisional, not a claim over C's migration. After the nonconflicting C handoff/main integration, pin and update the final revision/down_revision, add exact-head backup compatibility through the established consumers, rerun the migration/identity proof, and obtain CTO/CEO plus the owner's one-tap sign-in approval. No foreign parity file was edited or copied here. Do not ship the schema before those controls are satisfied.
