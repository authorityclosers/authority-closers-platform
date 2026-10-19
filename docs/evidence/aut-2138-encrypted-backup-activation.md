# AUT-2138: corrected encrypted backup source and activation packet

Status: **implementation in progress; no source admitted and no host apply**.
This record describes the source boundary and the evidence obtained locally.
It is not an activation approval or a passing database recovery proof.

## Verified baseline and implemented primitive

Candidate `62ed2bdb715acca37268bc0807eb38117469028e` contains the uploader,
helper and 23 focused tests. Its helper SHA-256 is
`f1f2d5e53b7fdde542f6f6a1ea5ccc1a35ebe6b9f98c234f6739afbd7b383dcc`.
Independent fictional reproduction on 19 October confirms both review findings:
corrupt the uploaded remote receipt to `{}` and upload still reports `passed`,
while fetch refuses `ciphertext_receipt_mismatch`; a child returning 2,097,152
stdout bytes is accepted. No real database or transport was used.

The new `infra/vps-foundation/scripts/drive_backup_process.py` provides one
shared monotonic deadline, actual streaming byte limits, exclusive private
download creation and removal of failed downloads. Child environments omit
secret variables, passphrases use stdin, stderr is discarded, and errors use
fixed codes. Each child starts its own process group; timeout, overflow, failure
and successful exit clean up that group without signalling unrelated groups.
This primitive is integrated into both source copies for upload and fetch.
The package remains unadmitted and is not installed on a host. It requires a manifest entry when the supported source package is
completed.

Focused validation: 36 tests pass (23 existing candidate cases and 13 new process
cases); Ruff, formatter and `uv run python -c "import ac_platform.http"` pass.
The new cases cover actual oversize output to memory/file, exact and zero-byte
limits, secret environment exclusion/stdin delivery, fixed errors, partial-file
cleanup, preservation of existing files, the shared operation deadline, owned
descendant cleanup and survival of an unrelated process.

Reproduction source, output, raw check logs and machine receipt are retained in
`/home/acdev/strikes/2138/`. Final source pins and uploadable evidence are recorded
on the issue as they become available.

## Ownership and remaining integration

Root transferred all five candidate source/test paths at preparation commit
`dabd2b11b8d96c97748e6c25f5727944c3ee1015`; their initial SHA-256 values matched
the transfer. Root retains host execution. The call-data reply relinquishes
consumer constant edits to Platform while other owners' parity work is preserved.

Required integration before review:

- Route **every** subprocess through one operation deadline. Download with
  bounded streaming stdout into an exclusive file; an advisory remote size is
  insufficient. Bound directory listings and all other captured stdout.
- Fetch and parse the remote receipt as well as the remote ciphertext after
  upload. Validate their exact identity, bytes and SHA-256 before reporting
  success; reject malformed JSON and partial object pairs without overwriting
  existing objects.
- Validate the dedicated environment key before capture. Bound capture,
  scratch and failure retention, preserve the newest verified point, and keep
  exactly 24 local points and the existing 14-day remote policy. Recognize only
  the writer's owned snapshot entries; refuse unknown entries rather than
  deleting shared files. Do not delete historical remote backups as part of
  repair or testing.
- Retain same-snapshot metadata in a reviewed archive revision. Reuse the
  canonical exported-snapshot holder, `capture_dump` and `source_row_counts`;
  never attach later counts to an existing dump. A legacy four-file snapshot
  cannot establish row-count parity.
- Obtain the call-data owner's committed proof/drill alignment to 67,108,864
  bytes, with >8/<64 MiB and exactly64 acceptance, >64 refusal and corruption
  refusal. Preserve all foreign edits. Full staging sizing remains AUT-2130
  followed by AUT-2131.

## Supported installation boundary

The existing `install-foundation-release.sh` accepts a commit-bound Git archive
of `infra/vps-foundation` and a release manifest. Its backup-only scope skips
application activation, Compose reconciliation and the foundation current-link
change. It takes the shared
`/srv/authority-closers/application/.deployment.lock` non-blockingly. It has **no
host dry-run option**. There is **no `ac-release install-host` command**.

The candidate files in `scripts/ops` are outside that archive and have no
manifest or backup-scope entries. A supported repair must place its canonical
uploader/helper and process primitive inside the reviewed foundation package,
or extend packaging with equally explicit source/target admission. Do not copy
uncommitted worktree files into an immutable release. Preserve the existing
backup-scope restriction; do not enable schedules or broaden app deployment.

The automatic rollback currently removes installed targets and extracts their
preimages. **Restoring a plaintext uploader is unsafe.** A final package must
refuse an unapproved predecessor before mutating targets and demonstrate failure
containment for the known legacy uploader. A new encrypted predecessor needs
exact source/hash review. If the first encrypted installation needs a timed
pause, CEO/operator must record its expiry, coverage, affected effective units
and failure behavior; Root executes it separately. No automatic plaintext
resumption is acceptable. This record does not introduce a pause or a hold.

The final fixture rehearsal must use the real transactional installer with
`AC_TEST_MODE=1`, an absolute isolated `AC_INSTALL_ROOT`, a
`foundation-test-...` release ID, full `AC_RELEASE_GIT_SHA`, exact
`AC_RELEASE_ARCHIVE` and `AC_RELEASE_ARCHIVE_SHA256`, and
`AC_INSTALL_SCOPE=backup`. Exercise `AC_TEST_FAIL_AFTER_INSTALL=1` and verify
target bytes, ownership/modes, rollback containment, unchanged current link,
unchanged Compose/app files and no schedule activation. This is a fictional
fixture rehearsal, not a host dry run.

## Admission and activation evidence still required

Only CEO/current release operator admits sensitive source and records the exact
invocation. Root retains AUT-2133/AUT-63 execution ownership. No present source
or command is approved for installation.

Before the final packet is reviewable, it must contain:

1. Final owner commits, per-file SHA-256, deterministic Git-archive SHA-256,
   manifest sources/targets/modes/root:root ownership, archive verifier checks,
   focused tests and an independent exact-source verdict. Pin the repaired
   foundation proof separately from the immutable application drill; the latter
   follows the current operator's normal application release route.
2. A non-mutating preflight that inventories/backups the exact installed uploader
   (`1cd4e3c80a4c593948b758e902c6f7ac4614b8b751394daa3fe467fa5dc162a5` baseline),
   modes, owners, ACLs and effective unit configuration. Refuse source or host
   drift. Backup creation itself belongs to the separately authorized Root run;
   it is not part of this issue's local execution.
3. Key custody validation for independent random >=32-byte secrets per
   environment in Infisical and the team password manager, without printing or
   retrieving live values here. Record secret names/versions and recovery
   custody checks, never values. Keys are not interchangeable between staging
   and production.
4. Release/backup exclusion locks and actual free-space reservation. At the
   Drive-only 512 MiB ceiling, reserve roughly 3 GiB for source plus upload
   workspace, in addition to retained copies; measure the final implementation's
   peak before admission. Do not widen the shared R2 restore consumer.
5. Exact reviewed preflight, fixture, apply, read-back and safe rollback commands
   with actual pins. Do not fill missing pins with a movable HEAD or present a
   future command as executed.
6. One upload/fetch/database proof per separately authorized environment, with
   run IDs, digests, timings, exact image/schema, same-snapshot counts, internal
   networking, no published ports/providers/workers, and labeled cleanup.

The smallest production proof begins with the existing canonical writer's
`--environment production --capture-only --dry-run`, then its approved
`--environment production --capture-only` pair. Installed proof and immutable
drill must use that same pair and exact application image/schema. This proves
only that pair. A Drive restore needs metadata captured with its own exact dump
in the newly reviewed archive revision; decrypt/hash alone is insufficient.

No host action, historical deletion, new provider/account/schedule, budget
change, app promotion, hold edit or disk encryption occurred in this work.

## Transport integration verification — 19 October 2026

Both helper copies now use bounded stdout for all subprocesses. Remote reads use
`rclone cat` into an exclusive private file; advertised sizes are advisory. One
900-second monotonic deadline covers upload/fetch, including hash/extraction
loops. GnuPG output also streams through the byte cap; stderr is discarded and
its process environment excludes secrets. No child can write the download path
directly. Both ciphertext and remote receipt must round-trip before success.
Malformed/non-object/mismatched receipts refuse; partial remote pairs stay in
place and subsequent attempts refuse overwrite. Temporary paths are scoped to
this invocation and removed on failure. Scratch requires three maximum archives
plus 64 MiB free; upload removes the original tar and ciphertext as soon as each
is superseded, bounding the maximum workspace to three archive equivalents.

Fictional focused validation: 46 PASS (33 helper + 13 process cases), including
actual oversized child streams for listing/cipher/receipt with a lying size
advertisement; corrupted remote receipts; partial upload; shared stage deadline;
private scratch cleanup; and real GnuPG round-trip. Capture/retention, same-pair
metadata, consumer alignment and installer rollback remain unfinished. These
checks establish transport behavior only; no database recovery is claimed.
