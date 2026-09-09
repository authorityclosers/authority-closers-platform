# Isolated localhost PostgreSQL runtime — 2026-09-07

## Verified result

PostgreSQL 18.6 is running on **127.0.0.1:55432**, with separately initialized **ac_platform** and **ac_local_sandbox** databases, in this worktree's ignored .tmp/local-platform/postgres directory. The launcher verified connections independently as ac_runtime, ac_migrator and ac_backup to both databases, checked the server's actual data_directory against its managed directory, and checked that the sole listener is IPv4 loopback.

The startup/ready command is scripts/Start-LocalPostgres.ps1. Re-running it completed successfully without replacing data or changing the listener. Its optional -Stop action addresses only this explicitly marked local cluster. No migration was applied by this setup task; the parent orchestrator owns local schema/API initialization.

Existing PostgreSQL remnants under Program Files, Docker, WSL, staging, production, and VPS databases were not changed. No production data was imported. The four credentials are the repository's existing explicitly local-only examples from .env.example and infra/local/postgres/init/001-roles.sql; readiness output contains no credentials.

## Runtime provenance

The official [PostgreSQL Windows download page](https://www.postgresql.org/download/windows/) directs portable-binary users to the [EDB binary archive page](https://www.enterprisedb.com/download-postgresql-binaries). Its 18.6 Windows link, https://sbp.enterprisedb.com/getfile.jsp?fileid=1260488, redirected over HTTPS to:

https://get.enterprisedb.com/postgresql/postgresql-18.6-3-windows-x64-binaries.zip

Downloaded size: 344,414,106 bytes. Observed SHA-256, now pinned in the local launcher:

59f8ce701c63c2ed623c665a5e51b3ef6f2e37ccf837b68ffeed0742d0ae6abd

The runtime is isolated under C:/Users/Suyash/AppData/Local/AuthorityClosers/local-postgres-runtime/postgresql-18.6-3. Only the server bin/lib/share trees and relevant server/command-line licenses were extracted; pgAdmin and StackBuilder were not installed. postgres --version returned PostgreSQL 18.6. The launcher separately pins the four executed program hashes.

The distribution did not return a published checksum at the .sha256 or .sha256sum endpoints, and its four inspected executables reported NotSigned. This evidence establishes official HTTPS origin and repeatable observed checksums, **not** a verified publisher signature or independently published checksum.

## Safety and initialization

The launcher accepts a local port, not a host or arbitrary database directory. It rejects unmarked existing clusters, marker/worktree/port/runtime/role-contract mismatch, reparse ancestors, occupied ports without a matching local marker, and an unexpected server data_directory. It creates a new SCRAM-authenticated cluster with listen_addresses=127.0.0.1, then applies the checked-in role initialization contract transactionally to the new local database.

Child processes use explicit argument arrays, no visible windows, cleared inherited PG environment overrides, and bounded waits. Raw SQL, password-bearing environment, and raw stderr are not echoed. The temporary initialization password file is removed through its exact owned path. The initial Windows pg_ctl process exited while its detached server retained pipe handles; the launcher now bounds pipe EOF waits. Only the waiting launcher was stopped, preserving the newly created server, and the resumed launcher completed role initialization and all readiness checks.

Authoritative usage references: [initdb](https://www.postgresql.org/docs/current/app-initdb.html), [pg_ctl](https://www.postgresql.org/docs/current/app-pg-ctl.html).

## Local tests and remaining scope

Six offline launcher contract tests passed, including PowerShell parsing without launching a database. Tests cover exact runtime pinning, local-only data/role boundaries, bounded hidden child processes, environment clearing, path/extraction isolation, and separate fresh sandbox initialization. The actual ready path and idempotent re-entry were executed successfully. A mismatched-port invocation was refused while the original listener PID remained unchanged.

The parent initially migrated ac_platform under local policy, which correctly denied technical-validation publication. This setup did not modify that database's trigger, downgrade it, or repair its policy. At the parent's explicit direction, it created a second fresh ac_local_sandbox database. The sandbox reuses only the existing checked-in database/schema/default-privilege grant statements, with its explicit database name substituted; existing roles remain unchanged. The parent owns migrating the new database under the existing test-only fixture policy and running its API locally. This setup task reports readiness, not migration completion.

The tests do not claim to be a security sandbox for mutually hostile processes running as the same Windows user. No PostgreSQL migration/concurrency suite or API/user-journey pass is inferred merely from database readiness. All project changes remain uncommitted and local-only.
