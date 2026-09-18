# Scanner temporary disk capacity and rollback

The earlier `MaxThreads 2` / `MaxQueue 2` policy and an 8 GB startup free-space
check did not enforce the claimed disk envelope. ClamAV 1.5.4 increases queues
smaller than twice the thread count on Linux, and INSTREAM creates a temporary
file before dispatching a scan. This follows the pinned engine's
[queue adjustment](https://github.com/Cisco-Talos/clamav/blob/clamav-1.5.4/clamd/server-th.c#L1387)
and [stream temporary-file creation](https://github.com/Cisco-Talos/clamav/blob/clamav-1.5.4/clamd/session.c#L587).

The exact scanner controller now prepares one retained
`/srv/authority-closers/media-safety/scanner-temp-v1.ext4` file with a fixed
8 GiB allocation. Initial allocation requires 10 GiB free: the image plus 2 GiB
host headroom. `posix_fallocate` reserves backing blocks; formatting disables
discard and lazy initialization. Existing image length, allocated blocks,
root ownership, mode 0600 and single link must match. An interrupted `.preparing`
allocation is retained and blocks another allocation; it is never silently
deleted or recreated.

The controller mounts only that image as ext4 with `nodev,nosuid,noexec`, checks
the exact loop device/backing path, zero offset, unlimited-to-file size, writable
mode, and exact block-device capacity. The container proof checks matching host
and container device/inode identities. The filesystem's metadata, active scans,
queued streams, extracted files and retained crash debris share the same 8 GiB
ceiling. The source remains capped at 2,000,000,000 bytes and scanner memory at
4 GiB. Effective `MaxQueue` is explicitly 4 with 2 threads. There is no promise
that every simultaneous maximum-size scan fits: full storage must produce a
scan error, never a clean result or increased host allocation.

The underlying unmounted directory is empty, root-owned and mode 000. If the
host reboots without this mount, a restarted UID 100 scanner cannot write an
unbounded fallback directory. After reboot, run the checksum-verified exact
controller's existing `start` command, then `prove`; disk-backed targets remount
and recreate only the scanner service. No global Docker/systemd configuration
is changed. A nonempty old unmounted directory is refused without erasure.
Old/socket-only rollback targets skip the new workspace requirement, including
when the host has less than 8 GiB free. Existing fixed images can be reused when
free host space is low; they are never reformatted to recover capacity.

The application installer continues to select the target release's own media
overlay and exact staging/production roots. The rollback fixture now executes
both target compositions and checks enabled-to-disabled, disabled-to-enabled,
and historical profiles without media keys. No application activation selector
is changed by this repair.

## Validation and remaining gates

Focused Windows tests exercise image/mount refusal, allocation failure retention,
reuse without reallocation, old rollback, mismatched container mounts, protocol
disk-error rejection and actual Docker Compose configuration in both rollback
directions. These are controller/protocol fixtures, not Linux mount or real
daemon acceptance:

- Scanner controller and client: **189 passed, 1 skipped**. The skip is the
  explicit Linux loop-filesystem proof on Windows.
- Application filesystem/profile/Compose selection: **9 passed, 84 deselected**.
- Ruff lint and formatting pass for all five changed Python files; Git diff
  whitespace validation passes.

The opt-in Linux test uses an isolated 32 MiB image and temporary mountpoint,
first asserting that the production constant remains 8 GiB. It fills the real
filesystem to ENOSPC, checks fixed allocation, unmounts to verify root mode 000,
and remounts to verify retained data without reallocation. It requires root,
CAP_SYS_ADMIN, and `mkfs.ext4`, `mount`, `umount`, `findmnt`, `losetup`, `blockdev`
(Ubuntu `e2fsprogs` and `util-linux`). Missing privileges/tools are explicit skips,
which do not count as an acceptance receipt. From the tested checkout:

```sh
sudo env AC_SCANNER_LOOPBACK_TEST=1 .venv/bin/python -m pytest \
  tests/infra/test_media_safety_temp_filesystem.py -q -r s \
  --junitxml=scanner-loop-filesystem.xml
```

Before activation, root must use the immutable scanner artifact on the intended
Linux host and prove: exact ext4/loop capacity and container mount, constrained
ENOSPC behavior, retained allocation across scanner restart, missing-mount
failure and controller remount after reboot, plus fresh signatures, PING,
clean and EICAR. The actual 2 GB film upload, scan, FFmpeg processing and private
playback remain separate deployment receipts. No VPS mutation, media activation,
large disk allocation, loop mount or real daemon test occurred in this change's
Windows fixture run.
