# Migration 20260930_0054: organisations

This forward-only migration adds the organisation registry, versioned verified
domain settings, and invitation records. It adds the `member` membership role
and `platform_organisations_manage` to the platform capability constraints.

The migration builds the same organisation tables and partial pending-invite
index on SQLite and PostgreSQL. Downgrade raises `forward-only`. Backup and
restore parity adds the three new tables at migration head `20260930_0054`;
earlier parity heads retain their original table inventories.
