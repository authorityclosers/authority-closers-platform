# Owner-approved data changes

Every script in this folder is an owner-approved data change under the
OWNER-APPROVED DATA CHANGES section of `AGENTS.md` and follows the same rules:
it is idempotent (a second run changes nothing), it runs as a dry run by
default and prints the state before and after, it applies the whole change in
one database transaction, and it writes an audit event that names the approver
and the issue. On production, take a database snapshot before applying. Within
2 working days, the same result must also be covered by a migration, seed or
Admin feature, so that no environment depends on hand-made state.
