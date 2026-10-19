# AUT-2138 — encrypted Drive backup source and host-maintenance packet

Candidate for independent security review and CEO/operator source admission.
**No host apply, secret access, provider operation or release was performed.**
Root retains AUT-2133/AUT-63 execution authority. This issue delivers reviewed
source and instructions; successful local tests do not establish live recovery.

## Source and ownership

Root transferred the original helper/wrapper/tests and both foundation copies in
`/home/acdev/strikes/2138/INBOX.md` at preparation commit
`dabd2b11b8d96c97748e6c25f5727944c3ee1015`. All five initial digests matched.
The bounded subprocess primitive began at `53d372f8`; transport integration was
committed at `c4c1f9ca`. Final source commit, per-file SHA-256, archive SHA-256 and
exact-head check receipts are in the attached `source-pins.json`. Source pins
are immutable commit IDs, never the current worktree or a movable HEAD.

Call-data explicitly relinquished the two size constants. Platform changed only
`MAX_DUMP_BYTES` in the foundation proof and `MAX_BACKUP_BYTES` in the application
drill from 8 to 64 MiB, matching the existing 67,108,864-byte policy. Other
owners' parity tables and migration entries remain unchanged.

## Corrected behavior

- Upload success requires both remote ciphertext and remote receipt to round-trip.
  Malformed/non-object/mismatched receipts and partial pairs refuse; an existing
  remote directory is never overwritten. No plaintext transport fallback exists.
- Every downloaded byte goes through capped stdout into an exclusive private
  file. Remote size is advisory. Listings and other child stdout are capped too.
  GnuPG writes through the same pipe, with a dedicated private home, no autostart,
  stdin-only key, stripped child environment and discarded diagnostics.
- One 900-second monotonic deadline covers capture, upload/fetch and their
  subprocesses. Owned process groups are cleaned on failure and success; no
  shared groups are signaled. Hash/extraction loops check the same deadline.
- Keys are required before capture; equal staging/production values refuse.
  Dry-run reads no secrets, runs no subprocess and creates no files.
- Capture reuses canonical `capture_dump`, exported-snapshot holder and
  `source_row_counts` through optional bounded I/O. Dump and counts use the same
  snapshot ID. A new encrypted v2 archive includes `metadata.json` from that pair
  alongside dump/checksum/schema/receipt. Old four-file snapshots may remain in
  local retention but cannot be uploaded as v2; later counts are never attached.
- The Drive dump/consumer cap remains a separate 512 MiB. Shared R2 proof/drill
  stay at 64 MiB. Fetch/decrypt/checksum is not a database restore proof. A Drive
  pair larger than 64 MiB needs the separately bounded DB consumer from
  AUT-2130 → AUT-2131; this packet does not widen shared restore policy.
- Failed capture leaves no published/temporary directory. After publishing a
  verified local point, rotation retains exactly 24, explicitly keeping that
  point even if the clock moved backward. Upload failure cannot postpone local
  rotation. Unknown entries or an already oversized ring stop another capture.
  There can be at most 24 plus one in-flight point if retention itself fails.
  Only validated snapshot members are removed, never arbitrary shared files.
- Normal successful capture keeps the existing remote `--min-age 14d` policy.
  The activation proof below uses `upload`/`fetch`, which do not run retention;
  no historical deletion is authorized by this issue.

## Supported installation scope

Use the existing transactional `install-foundation-release.sh` with the new
explicit `AC_INSTALL_SCOPE=drive-backup`. Its separate reviewed manifest is
`config/release/install-manifest-drive-backup.tsv`; its exact target allowlist
is `install-scope-drive-backup.txt`. Ordinary/full foundation and ordinary
backup-scope installs do not incidentally select the Drive files.

| Source under infra/vps-foundation | Target | Mode | Owner |
| --- | --- | --- | --- |
| scripts/drive-db-snapshot | /usr/local/sbin/ac-db-snapshot | 0750 | root:root |
| scripts/drive_postgres_backup.py | /usr/local/libexec/authority-closers/drive_postgres_backup.py | 0640 | root:root |
| scripts/drive_backup_process.py | /usr/local/libexec/authority-closers/drive_backup_process.py | 0640 | root:root |
| scripts/drive-backup-disabled | /usr/local/libexec/authority-closers/drive-backup-disabled | 0750 | root:root |
| scripts/ac-postgres-backup.py | /usr/local/libexec/authority-closers/ac-postgres-backup.py | 0755 | root:root |

The new scope changes no Compose, application route/current link, schedule or
service activation. It holds the existing application `.deployment.lock` and
records `foundation-scopes/drive-backup.release`. The foundation proof uses the
existing reviewed `backup` scope separately. The application drill enters the
normal immutable application release through the current ship operator; never
substitute a file in an immutable release or start a competing ship.

The installer has **no host --dry-run** and no `ac-release install-host` exists.
The only installer rehearsal is isolated `AC_TEST_MODE=1` with an absolute
fixture root and a test release ID. Do not copy those test variables to a host.

## Predecessor and rollback contract

The installed uploader baseline expected by the parent is
`1cd4e3c80a4c593948b758e902c6f7ac4614b8b751394daa3fe467fa5dc162a5`.
The installer requires the admitted source SHA and an exact installed uploader
SHA (or explicit `absent`). Drift refuses before any target mutation.

A previously reviewed encrypted predecessor additionally requires its exact
`AC_DRIVE_SAFE_PREDECESSOR_SHA256`. Ordinary transactional rollback restores its
bytes, mode/owner and ACL/xattrs. Do not label unknown code safe.

The known legacy plaintext predecessor additionally requires the reviewed
`AC_DRIVE_LEGACY_FAILURE_POLICY=disabled`. It is excluded from the automatic
preimage archive. Before replacing other targets, the installer atomically
replaces it with the fixed-code disabled guard. A failed transaction restores
other targets and leaves that guard at the uploader path; it never restores the
plaintext uploader, even temporarily. Recovery requires a separately admitted
retry or encrypted predecessor. The operator's private pre-change archive
retains the original bytes for evidence, not automatic execution.

CEO/operator must admit either the safe encrypted predecessor or a timed pause
and coverage record: exact effective triggering units/manual entrypoints,
start/expiry, alternate recovery coverage, responsible operator and what happens
at expiry. Failure leaves Drive disabled; expiry never resumes plaintext.
No pause, hold or schedule was changed here.

## Non-mutating preflight — Root records actual host facts before apply

Use the attached pinned package and `source-pins.env`; no key values belong in
that file. Resolve `AC2138_PACKET` to its verified delivery directory. Check its
published bundle digest before trusting files. These commands are read-only:

```bash
cd "$AC2138_PACKET"
python3 "$AC2138_PACKET/infra/vps-foundation/scripts/verify-git-release-archive.py" \
  "$AC2138_PACKET/foundation.tar" "$AC2138_ARCHIVE_SHA256" "$AC2138_SOURCE_SHA"
sha256sum --check --strict "$AC2138_PACKET/package-files.sha256"
bash -n "$AC2138_PACKET/infra/vps-foundation/scripts/install-foundation-release.sh"
sha256sum /usr/local/sbin/ac-db-snapshot
stat -c '%n %a %u:%g %h' /usr/local/sbin/ac-db-snapshot
getfacl --absolute-names /usr/local/sbin/ac-db-snapshot
systemctl list-unit-files --no-legend 'ac-*'
df -PB1 /srv/authority-closers/backups
du -sb /srv/authority-closers/backups/staging-snapshots \
  /srv/authority-closers/backups/production-snapshots
python3 "$AC2138_PACKET/infra/vps-foundation/scripts/drive_postgres_backup.py" \
  capture --environment staging --label aut-2138-preflight
```

Repeat file digests/stat/ACL inventory for every target and its parent directory,
including absent targets. Record exact effective uploader-triggering units,
fragments/drop-ins, active/enabled state, ExecStart and effective sandboxing;
store raw units privately because they can contain credentials. Never print
unit Environment fields or publish raw configuration. Pin the resulting
inventory digest in admission and compare it immediately before apply. Any
byte, metadata, unit or application image/schema drift requires a fresh review.

Check that the existing `.deployment.lock` and
`/run/lock/authority-closers/ac-postgres-backup-ENVIRONMENT.lock` are available
nonblockingly. The helper and installer acquire those locks for their actual
work; a preflight lock probe alone does not reserve the later window. Root
must record no overlap with the current release operator.

Measure actual free space, retained bytes and other in-flight reservations.
Helper scratch needs `3 * (512 MiB + 1 MiB) + 64 MiB` = 1,680,867,328 bytes
free at workspace entry, in addition to existing retained source points. Budget
one extra 512 MiB capture before its upload reservation and existing local
retention (24 points, up to 12 GiB plus sidecars). Peak upload/fetch workspace
is bounded to three archive equivalents; failed workspace files are removed.
The free-space check is not a filesystem reservation against unrelated writers;
Root must reserve the measured headroom operationally or stop, never free disk
by deleting shared/history files.

## Key custody and private pre-change backup — separately authorized Root run

Before capture, CEO/operator records the two dedicated names
`AC_POSTGRES_DRIVE_STAGING_PASSPHRASE` and
`AC_POSTGRES_DRIVE_PRODUCTION_PASSPHRASE`, secret versions and environment paths.
Each must originate from at least 32 cryptographically random bytes, be distinct,
and be independently recoverable from Infisical and the team password manager.
Custodians validate a private encrypt/decrypt challenge in each environment and
record only pass/fail/version/digest, never a value. Do not retrieve keys here,
print them, place them on argv, or copy a production key to staging.

Root backs up the exact installed target bytes plus parent/target modes, numeric
owners, ACLs/xattrs and effective unit configuration in a root-private run
archive, hashes it and records its path/digest on the parent. That creation is a
host write and must follow parent authority; it was not executed here. The
pre-change archive is not an approved plaintext rollback path.

## Exact invocation forms — admission must pin variables and authorized environments

`source-pins.env` fixes `AC2138_SOURCE_SHA`, `AC2138_ARCHIVE_SHA256` and the
baseline uploader digest. `AC2138_PACKET` is a private verified package directory,
not a mutable checkout. The CEO/release operator records the complete expanded
invocation and inventory/pause/coverage pins. Root applies it separately.

```bash
AC_INSTALL_SCOPE=drive-backup \
AC_RELEASE_ID="foundation-$AC2138_SOURCE_SHA" \
AC_RELEASE_GIT_SHA="$AC2138_SOURCE_SHA" \
AC_RELEASE_ARCHIVE="$AC2138_PACKET/foundation.tar" \
AC_RELEASE_ARCHIVE_SHA256="$AC2138_ARCHIVE_SHA256" \
AC_DRIVE_ADMITTED_SOURCE_SHA="$AC2138_SOURCE_SHA" \
AC_DRIVE_EXPECTED_UPLOADER_SHA256="$AC2138_BASELINE_UPLOADER_SHA256" \
AC_DRIVE_LEGACY_FAILURE_POLICY=disabled \
bash "$AC2138_PACKET/infra/vps-foundation/scripts/install-foundation-release.sh"
```

For a reviewed encrypted predecessor, replace the last policy variable with
`AC_DRIVE_SAFE_PREDECESSOR_SHA256` set to that reviewed predecessor's exact hash;
use that same hash as EXPECTED. For a genuine first install, EXPECTED is `absent`.
Never reuse the known plaintext hash as SAFE. No invocation is approved merely
because it appears in this candidate document.

Read back the selected manifest's five target digests, modes, root:root owners
and ACLs, and `foundation-scopes/drive-backup.release`; compare with source pins.
Recheck effective units, current links and application images/schema unchanged.
Use the helper's no-execute dry-run before any authorized upload/fetch.

## Recovery evidence — one separately authorized environment at a time

The smallest production proof starts with the canonical pair:

```bash
/usr/local/sbin/ac-postgres-backup --environment production --capture-only --dry-run
/usr/local/sbin/ac-postgres-backup --environment production --capture-only
```

Root records the exact new atomic dump/metadata pair, run ID, source app release,
image/schema and both digests. This command does not print the pair location;
select the newly created verified pair while holding the same environment lock,
not an arbitrary newest filename. It proves only that pair. Do not relabel an old
dump or later counts. The installed off-site proof normally selects a fresh R2
pair; it must not be claimed to prove this capture-only/Drive pair automatically.

After the normal ship operator releases the size-corrected immutable drill, use
its documented `--environment`, `--backup`, `--backup-metadata`, `--evidence-dir`
and exact `--application-image`, first without execute, then with
`--execute --acknowledge-isolated-target`. Metadata filename must be the drill's
bounded `backup.json` pair (copy the same metadata bytes; record their digest).
Use the same application release/schema; no source-checkout substitution.
The variables below are the exact paths/image digest saved by Root's authorized
preflight, not a current-link lookup performed midway through a proof:

```bash
python3 "$AC2138_IMMUTABLE_DRILL" --environment production \
  --backup "$AC2138_DUMP" --backup-metadata "$AC2138_METADATA" \
  --evidence-dir "$AC2138_EVIDENCE_DIR" --application-image "$AC2138_APP_IMAGE"
python3 "$AC2138_IMMUTABLE_DRILL" --environment production \
  --backup "$AC2138_DUMP" --backup-metadata "$AC2138_METADATA" \
  --evidence-dir "$AC2138_EVIDENCE_DIR" --application-image "$AC2138_APP_IMAGE" \
  --execute --acknowledge-isolated-target
```
Require an internal disposable network, no published ports, providers or
workers, and cleanup restricted to that drill's exact labels. Save its run ID,
image/schema, dump/metadata digests, source/restored row counts, times and labeled
cleanup result. A failed/missing parity proof is not upload success.

For Drive verification use one new v2 snapshot, generated with the canonical
same-snapshot capture, and the installed helper:

```bash
python3 /usr/local/libexec/authority-closers/drive_postgres_backup.py upload \
  --environment staging --snapshot "$AC2138_SNAPSHOT"
/usr/local/sbin/ac-infisical-run-backup -- python3 \
  /usr/local/libexec/authority-closers/drive_postgres_backup.py upload \
  --environment staging --snapshot "$AC2138_SNAPSHOT" --execute
python3 /usr/local/libexec/authority-closers/drive_postgres_backup.py fetch \
  --environment staging --snapshot "$AC2138_SNAPSHOT" --destination "$AC2138_FETCH_DIR"
/usr/local/sbin/ac-infisical-run-backup -- python3 \
  /usr/local/libexec/authority-closers/drive_postgres_backup.py fetch \
  --environment staging --snapshot "$AC2138_SNAPSHOT" --destination "$AC2138_FETCH_DIR" --execute
```

Root must create a run-owned empty mode-0700 fetch directory only after
permission, then use the same dump/metadata in the isolated DB proof above.
Repeat for production only with separate environment permission and key custody.
For >64 MiB Drive pairs, the shared drill refuses; the dedicated larger consumer
is a separate required output under AUT-2130/AUT-2131, not a policy exception.
Record the actual snapshot name, remote receipt/cipher hashes, operation timings,
DB proof and exact-label cleanup before claiming environment recovery.

## Verification and admission state

Focused fictional subprocess, real local GnuPG, same-snapshot metadata, repeated
failure/retention, both consumer boundary, transactional install and rollback
checks are retained in the attached verification logs. The fixture installer
makes no systemctl/docker/curl/provider calls, does not change the current link,
and verifies selected bytes/modes against the manifest. Fixtures do not prove
host ownership/ACL inventory or production recovery.

The attached source pins and archive need an independent exact-source review,
then CEO/operator admission of this maintenance package and invocation. No
current candidate is approved for installation. No historical deletion, new
provider/account/schedule, budget change, app promotion, hold edit or disk
encryption is authorized here.
