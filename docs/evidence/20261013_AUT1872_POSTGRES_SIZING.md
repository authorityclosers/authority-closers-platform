# AUT-1872 — bounded PostgreSQL sizing source

Source-only diagnostic, fictional verification. Production invocation remains on AUT-1873 after independent CTO review and CEO exact-source authorisation. The 11 October workbench order replaces obsolete lane/branch/PR admission; this source is built in shared dev/live with only the claimed script and new tests. Foreign edits are preserved.

Controlled inputs: snapshot-repair-decision revision 99c9862d-323b-4619-a2f0-53f4b18f851c (body SHA256 0c6359aa958d7df331bf56614c7b2d4a5d18b7b7e5a56198c537cb33a805450c); bounded-sizing-receipt revision 23cd122c-de77-4f9d-8ac8-5b57827a4374 (body SHA256 57e1f44a5ecfde07b599bc60f897fcfb7bbf17c419b345fe5bc5f2fc4fb74da2). Both exact revisions were read and digests matched. No installation archive digest is asserted.

Pinned admission

- Application and backup-scope commit fa846dc1264130e295eccc13daf6164c673c8a8a. Installed backup Python bytes must hash to fea361c9883d603b0fae78c8081b4492be965afeb65ac619448ca2556aa294cf before any import. No pycache is written by that loader.
- Existing backup.release must contain the exact foundation scope. Policy bytes must hash to bd04b1397a802ec8923e3e488d3b1a2fea8454219aae4ea19ad5ee151ce84846. Existing canonical release checksum/profile/image admission is reused.
- Exact schema head 20261011_0087 / ac-postgres-parity-v58 / 149 canonical parity tables come from that approved backup source. Public table/view/foreign/materialized relation inventory must equal the approved ordinary-table inventory; unexpected, missing or substituted relations refuse. This is the existing migration-identity/table-inventory schema contract, not a column-by-column schema attestation.
- PostgreSQL server version must be 180006. Existing ac_backup role must have SELECT/USAGE and no table-write privilege, superuser/createdb/createrole/inheritance/replication/bypass-RLS flags. RLS filtering is refused with row_security=off. No grants, schema changes or role changes occur in the diagnostic.

Operation

Dry-run is default: release/policy/source/inventory validation only, no connection or secret injection. Explicit --read sends only generated fixed SQL on stdin through the existing Infisical/compose transport. Credentials are injected at runtime; no values or DSNs in argv, receipts or errors. Alternate libpq host/options/service variables are unset; fixed localhost:5432, role and existing container database are used.

One REPEATABLE READ, READ ONLY transaction admits role/schema/inventory before counts, outputs database bytes plus 149 heap/index/total-byte and parity-count records, then ROLLBACK. Counts share its MVCC snapshot. Physical byte observations are contemporaneous storage observations; they do not establish complete pg_dump bytes, compression ratio, growth rate or restore success.

Limits are fixed: 1024 relation/counter records, 1 MiB buffered raw/final receipt, 1s lock, 10s statement, 5s idle transaction, 2s connection and 60s overall operation. A container-side timeout kills its whole diagnostic group after 55s; the local supervisor owns a new process group and kills it on every exit, reserving 1s for cleanup. Early local cancellation can leave the container-side invocation alive until its independent watchdog expires, always within the overall 60s envelope. No limits are adjustable.

All error output is suppressed and converted to fixed reason codes. No partial receipt is published. JSON rejects excess/missing records, duplicate keys, unexpected fields/names, non-integer/negative/excessive counters, invalid time/version/read-only markers or contradictory sizes. Application/policy pins are checked again before publication. Scratch SQL lives in an anonymous run-owned temporary file and closes on every path. Rollback is read-only transaction rollback, connection closure and process exit; no persistent installation or production state change is needed.

Verification

- Initial unit pass reached 32 before an immediate-after-SIGKILL assertion raced kernel exit. The assertion now waits for the pidfd exit event within 1s; no runtime timeout was increased.
- Initial PostgreSQL read-only-write proof used an unqualified fixture table while the exact setup deliberately sets search_path=pg_catalog; corrected the fictional INSERT to public.persons, retaining the read-only error assertion.
- Focused unit plus actual PostgreSQL integration: 46 PASS / 22.20s before the final role-inheritance and scratch/environment hardening. Final script/SQL checks: 46 PASS / 20.25s (36 unit, 10 actual PostgreSQL), JUnit SHA256 28729a5fe2486d4d54ec5a3cb9c66a4928c10c804c308decad6d0e27a53d9b0c. Ruff formatting/check, API import and scoped whitespace checks passed. The integration URL now also accepts the existing standard CI runtime variable names; the final integration-only recheck is recorded in the handoff.
- PostgreSQL 18.6 (server_version_num 180006), psycopg 3.3.4; existing public fictional loopback CI service referenced by ac-strike-run. Tests create only run-owned ac_test_sizing_* databases and a temporary reader role if absent; existing canonical roles are reused unchanged, and all owned databases/temporary roles are removed in fixture cleanup. No production connection or privileged host command occurred.
- Ten actual PostgreSQL cases prove full inventory counts and expected sizes, read-only write refusal and rollback, schema/head/inventory/read/write-privilege refusals, real 1s lock/10s statement timeouts, counts under concurrent committed writes and total-timeout connection closure. Thirty-six unit cases prove source admission, limits/unsafe output/redaction, dry-run/no-connect and process-group descendant cleanup.
- Integration executes the exact generated SQL in a psycopg child using the real bounded supervisor. It substitutes for Docker/psql transport, which was not invoked here. Deployment, installed psql/coreutils capability, release headroom/overlap and live pins are separate operator admissions. Hosted exact-source CI and CTO/CEO approval remain required; no green CI, approved invocation or production measurement is claimed by these local tests.

Next: publish the full source commit/digests, fixed SQL/inventory pins, exact two invocations and allowlisted receipt in this issue's source-handoff document; retain the source bundle/JUnit as Paperclip work products; use the existing native CTO then CEO stages. The later operator must refuse any changed live pin and get a separately reviewed rebinding before reading. Shipping remains the sole authorised coordinator path; no builder PR, push or competing ship is created.

Exact script SHA256: 915fc6be80aaec0a2d903bcdadba7d8198d6cdb8736fa1ab2a08776b5adbbc29. Fixed SQL SHA256: 8aed056ccb6bfc2ee52ea62417ad7f91e2ccf713c58af7ed17b7e631fc177b8a. Ordered approved inventory JSON SHA256: f405624d9a9632ece77c0f8b979ec5be6a1782367ad54f702fcb9cd00a5624aa. Full source commit is recorded in the task handoff after the ownership-safe wb-commit.

Final receipt-only refinement: fixed short labels for malformed-output test cases prevent a 1 MiB synthetic parameter from expanding JUnit case names. Runtime/SQL bytes are unchanged. Final unit36PASS; integration10PASS/19.94s; compact XML receipts are included in the source bundle.
