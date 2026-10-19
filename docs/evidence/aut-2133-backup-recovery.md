# AUT-2133 backup recovery — 19 October 2026

**Disposition: encryption source prepared, not live; no passing current database
restore drill claimed. Disk encryption is a proposal only.** Root standing
authority: [AUT-63](/AUT/issues/AUT-63); operator run
`6ad720ff-ef66-4ac1-9e84-7a4c8ba3e06e`. All privileged observations/invocations
used the audited `ac-root` entry point, whose check exited 0. No release,
service restart, production SQL, data edit, secret provisioning, purchase,
provider activation or hold-file change occurred.

## Live findings

- Production core/web: `4d228216053890999a4629433793ba08a6d06252` (v0.65.0).
  Staging: `66ebf3080ba35b46308e559d866f86bbb1da6481` (v0.66.0).
  Both current immutable release manifests have no missing/extra files and
  every listed SHA-256 matches at this observation. The 18 October production
  proof failed on unmanifested files in the then-current release; do not delete
  historical evidence or weaken the manifest check to clear it.
- Live `/usr/local/sbin/ac-db-snapshot` uploads its entire plaintext snapshot
  directory through rclone to `acdrive:AC Backups/postgres/<environment>/...`.
  Production is hourly; staging six-hourly. Existing retention is 24 local
  snapshot directories/environment and 14 days on Drive.
- Pulse's separate hourly backup is already GnuPG-encrypted. It is not the
  application database backup, and its key must not be reused.
- The 18 October foundation restore failed with `no space left on device` at
  approximately 04:20 UTC; journald suppressed another 41,962 messages. It
  restores a full host snapshot into `/tmp` on the same disk. At observation,
  `/` has 206,900,281,344 bytes total and 23,133,638,656 available (89% used).
  Application releases ~23 GiB, release store ~9.6 GiB, volumes ~15 GiB, backups
  ~12 GiB, media safety ~8.1 GiB. Do not rerun this full expansion into the
  existing free space, delete shared files, or silently replace it with a
  partial restore while claiming full-host recovery.
- Existing staging writer/proof failure and governed repair are already on
  [AUT-2130](/AUT/issues/AUT-2130), with source/measurement output on
  [AUT-2131](/AUT/issues/AUT-2131). No second sizing run or policy increase was
  attempted. The approved R2 policy remains 64 MiB/dump, 336 retained
  points/environment and the existing spending/storage envelope.

## One new production proof, failed safely

`systemctl start ac-restic-postgres-restore-proof@production.service` ran once,
07:44:50–07:45:13 UTC, exit 1. Invocation ID:
`daeb717520794d0caeeb82a6808adc13`. Error:
`logical backup metadata size or digest does not match`.

Both consumers have a hardcoded **8 MiB** ceiling:
`ac-restic-postgres-restore-proof.py:MAX_DUMP_BYTES` and
`restore-drill.py:MAX_BACKUP_BYTES`; the writer already admits **64 MiB** by
approved policy. A current local logical pair, capture
`20261019T074542.319266Z-70742-production`, contains a **14,183,002-byte** dump,
recorded and actual sizes equal, SHA-256 equal, with 159 row-count inventory
entries and the exact current production release. That confirms a real
consumer/writer bound inconsistency. The exact off-site pair selected by the
failed invocation was cleaned by the proof and has not separately been
attested; do not call this a proven corruption incident or a successful restore.

The current owner of the modified parity sources received an exact INBOX
request to align these two consumers with the existing approved ceiling and
test >8/<64 MiB acceptance and >64 MiB rejection. Root left every foreign edit
untouched. A source-level repair still requires the governed release route
before a live proof can pass. Staging's ~112 MiB dump exceeds even that approved
ceiling and remains the separate existing repair output.

## Prepared encryption change

New source: `scripts/ops/drive_postgres_backup.py` and candidate host wrapper
`scripts/ops/ac-db-snapshot`. They are not installed and do not self-deploy.

- The wrapper retains existing pg_dump capture, verification and 24-local /
  14-day Drive rotation. It replaces plaintext directory upload with the
  encryption helper. Existing service serialization remains unchanged.
- Four existing files are packed privately, encrypted with GnuPG AES-256 and
  integrity protection. Only `backup.tar.gpg` and a ciphertext receipt go to
  Drive. The helper downloads the uploaded ciphertext, verifies its SHA-256,
  decrypts it, checks the plaintext dump hash and compares all four source
  files before reporting success. It never falls back to plaintext.
- Separate random secrets are required in AC's recovery vault:
  `AC_POSTGRES_DRIVE_PRODUCTION_PASSPHRASE` and
  `AC_POSTGRES_DRIVE_STAGING_PASSPHRASE`. Generate at least 32 random bytes per
  environment, store directly in Infisical and the team password manager,
  verify independent recovery custody, and inject via the backup identity.
  No key has been created or printed. GnuPG receives it via stdin, never argv;
  subprocess environments exclude the Infisical token and injected secrets.
  This symmetric design permits unattended drills; it does not provide the
  stronger separation of an offline-only private key.
- Helper defaults to a non-mutating dry-run. Execution requires root and
  `--execute`. Fetch refuses wrong environment/keys, unsafe paths, symlinks,
  hardlinks, extra archive members, oversized input and nonempty destination.
  Child diagnostics are suppressed and replaced with fixed refusal codes.
- Its 512 MiB transport cap applies only to the existing full Drive format;
  it does not change the R2 policy, retention, billing or provider settings.
- Existing plaintext Drive history is still plaintext and remains under its
  existing retention. No permanent deletion or re-encryption of historical
  objects is authorized by this candidate. A partial failed upload also needs
  an explicit recovery action; it will not overwrite an existing remote path.

23 focused tests passed in 1.98s, including actual GnuPG encryption/decryption
of fictional data, a wrong-key rejection, ciphertext tampering, no plaintext
upload, path/archive attacks, source checksum failures, environment separation,
redaction and dry-run behavior. Transport uses a controlled local fake in these
tests: **no real Drive upload or PostgreSQL restore has been proved**. Initial
verification retained: 22 pass/1 test-mock permission failure, fixed to create
its fake ciphertext privately; lint/import-order/format findings corrected.
Ruff check/format, shell syntax, API import and scoped whitespace checks pass.
The current writer's old receipt has no exported-snapshot row-count inventory;
a future full Drive database drill must capture counts in the same MVCC snapshot
as the dump rather than compare against a moving production database.

## Activation, read-back and rollback contract

Independent security review and source admission must precede installation.
The release/operator owner must provide the supported pinned host-maintenance
activation route; do not hand-edit production files or install from an
unreviewed worktree. Before replacement, save and hash the current uploader,
unit definitions and relevant mode/ownership in a root-only run directory.
No service restart or timer-cadence change is needed for a reviewed uploader
replacement. Preserve all `/etc/ac-release/production.HELD-*` markers.

The activation transaction must verify source bytes, secure key custody and
helper availability before replacing the uploader atomically. Dry-run first.
Run one explicit encrypted upload in each required environment, retain
ciphertext paths/run IDs/digests/timings, fetch/decrypt it, and run the sanctioned
isolated PostgreSQL restore with matching snapshot row counts, exact schema,
application health and labeled cleanup. A decrypt/hash round trip alone is
not a database restore. Do not enable a second job schedule.

Rollback must leave existing local/remote backups intact. If encryption cannot
run, fail the upload and alert the operator. Restoring the old plaintext
uploader as an automatic fallback is unacceptable; an authorized operator must
choose a reviewed encrypted predecessor or pause this uploader with a recorded
expiry/coverage decision. Existing Restic backups remain independent.

## Disk encryption option — no execution requested

The host has one 200 GiB virtual disk, one root ext4 data partition, no LUKS
mapping and no free data partition. `cryptsetup` is installed; ext4's `encrypt`
feature is not enabled. No provider account setting was changed or purchased.

**Lowest software cost:** LUKS2 costs no additional licence fee. A file-backed
LUKS2 data volume on this VPS is feasible only after creating enough capacity
for the encrypted target, its copy and rollback margin. A full `/srv` migration
does not fit the current ~22 GiB free space; claiming a safe zero-cost in-place
conversion today would be misleading.

**Practical capacity option:** obtain an account-specific quote to move from the
200 GiB KVM 4 capacity to 400 GiB KVM 8, then preallocate a sufficiently large
LUKS2 data image and mount it for the approved persistent-data and backup paths.
Keep OS/boot separate. Public India renewal rates observed 19 October are
₹2,399/month (KVM 4) and ₹4,399/month (KVM 8), an indicative **₹2,000/month
increment**, prepaid for the plan term. Promotional rates are ₹1,099 and
₹2,199/month respectively. These are public rates, not the account's upgrade
quote, tax, proration or a purchase authorization.
[Hostinger public pricing](https://www.hostinger.com/in/vps-hosting),
[plan capacities](https://support.hostinger.com/en/articles/6976044-parameters-and-limits-of-hosting-plans).

Plan **2–4 hours of service downtime** for a checked backup, stop of all writers,
final copy, mount/cutover, exact release restart, health checks and one encrypted
restore; this is an engineering estimate, not a measured migration. Disk growth
or provider maintenance may add downtime. The exact stop/restart list and
rollback must be approved before work starts. Rollback is to the untouched
pre-cutover data only before new writes; after new writes it needs a reconciled
restore, never a stale directory swap over audit history.

Main risks: key loss; failed unlock after reboot; a sparse/undersized loop image
filling the root disk; an unmounted target allowing plaintext writes; copying
live PostgreSQL files inconsistently; plaintext remnants on old blocks and
provider snapshots. Require fixed capacity, mount dependencies that fail closed,
separate recovery custody, verified unlock/reboot rehearsal and new encrypted
backups. Encryption while mounted does not protect against root compromise.
Existing plaintext blocks/snapshots are not retroactively secured by moving
files; a fully clean encrypted rebuild is needed before claiming that historic
media contains no plaintext. See the upstream
[cryptsetup documentation](https://gitlab.com/cryptsetup/cryptsetup/-/wikis/FrequentlyAskedQuestions).

**Potential ₹0 hosting alternative:** fscrypt can encrypt selected directories
on supported ext4, but this filesystem lacks its feature flag and existing files
must move into new encrypted directories. It is directory encryption with
metadata/old-block limitations, not full-disk encryption, and still needs space
and an owner-approved maintenance/unlock plan. It is not a drop-in fix today.
[Kernel fscrypt documentation](https://www.kernel.org/doc/html/latest/filesystems/fscrypt.html).

Hostinger's public trust material did not establish a VPS encryption-at-rest
setting or a customer-controlled encryption key. Provider-side encryption
availability, scope, key custody, cost and downtime remain **unverified**; do not
claim it is included. CEO may obtain written provider confirmation before
choosing it. [Hostinger Trust Center](https://trust.hostinger.com/).

The owner can choose later between the account-quoted LUKS2 capacity option,
a separately reviewed fscrypt design, a clean encrypted rebuild, or a provider
option once documented. This issue does not authorize any disk operation.
