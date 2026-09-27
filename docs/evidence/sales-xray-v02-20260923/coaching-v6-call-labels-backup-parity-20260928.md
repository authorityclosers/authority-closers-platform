# Coaching-v6 selection and call-label migrations: backup coverage

Migrations `20260925_0049` (explicit coaching-v6 settings) and `20260925_0050`
(owner-authored call-label revision history) are now recognised by the backup,
restore-proof and application restore-drill tools.

| Head | Contract | Tables |
|---|---|---|
| `20260925_0049` | `ac-postgres-parity-v29` | 100 (constraint change only, no new table) |
| `20260925_0050` | `ac-postgres-parity-v30` | 101 (adds `conversation_submission_label_revisions`) |

Historical head mappings are unchanged. These parity checks compare the migration
head and table row counts; they do not compare every column value or prove a live
restore.

Install the foundation tools from the same source before applying these
migrations in any deployed environment; the older foundation catalogue cannot
attest the new heads. No deployed state was changed by this work.
