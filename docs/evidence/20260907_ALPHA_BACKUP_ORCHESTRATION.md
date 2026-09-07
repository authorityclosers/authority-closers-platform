# Alpha backup/restore orchestration hardening — 2026-09-07

Status: repository implementation and isolated synthetic verification; **not a
production backup/restore acceptance claim**. Base checkpoint: `28b0c06`.

## Evidence and bounded diagnosis

Read-only `systemctl show` over the existing `ssh ac` connection returned only
allowlisted service properties, not command environments or secret files:

| Service | Observed state | Last recorded start / exit (UTC) |
| --- | --- | --- |
| `ac-restic-backup.service` | failed, exit status 1 | Sep 7 02:17:20 / 02:17:23 |
| `ac-restic-restore-check.service` | failed, exit status 1 | Sep 6 04:17:18 / 04:17:20 |
| `ac-postgres-backup.service` | activating at the observation | Sep 7 12:45:21 / not yet recorded |
| `ac-restic-postgres-restore-proof@staging.service` | failed, exit status 1 | Sep 1 03:32:34 / 03:32:50 |

A separate bounded journal read since September 6 returned only counts of two
fixed, allowlisted messages from at most 1,000 journal entries: one immediate
Restic contention message and four encrypted off-host logical-upload failure
messages. These bounded counts are not an exhaustive incident count. No raw
journal output, credentials, environment-file contents, SQL, or database data
was collected into this evidence.

Source inspection confirms that the shared repository lock immediately rejected
contention in each scheduled shell entry point and in the Python logical-upload
path. The off-host path discarded all stderr and supplied only a generic failure,
so its precise remote/provider/descriptor failure cannot be established from the
old logs. A missing inherited descriptor is now distinguishable; it is **not**
asserted to be the proven cause of those historical upload failures.

## Changes

- Foundation backup, foundation restore check, and logical restore-proof shell
  entry points wait up to 600 seconds for the same existing exclusive local
  repository lock. Timeout exits distinctly with status 75. Other acquisition
  errors fail immediately with a safe diagnostic.
- The Python logical-upload lock and standalone logical-upload shell path use a
  60-second maximum wait. Python retries only the contention errors `EACCES` and
  `EAGAIN`, using a monotonic deadline and bounded polling. Invalid descriptors,
  I/O, permission failures, and invalid wait bounds are not blanket-retried.
- Existing lock path, root/group ownership, descriptor/inode/link checks,
  symlink/no-follow protections, and exclusivity remain in place. The inherited
  descriptor path remains nonblocking because the parent must already own it;
  a closed descriptor receives a specific safe marker.
- Off-host stderr is continuously drained into an 8,192-byte in-memory tail,
  never persisted or echoed. Only fixed diagnostic labels and numeric exit
  status reach the operator-facing exception. Timeout, termination, local lock,
  R2 usage guard, remote lock, authorization, network, and unknown-command
  failures are distinguishable where the captured signature supports them.
  These are diagnostic categories, not authorization or automatic retry rules.
- A diagnostic-reader failure fails closed, and timeout/lingering child cleanup
  remains bounded to the subprocess group owned by this upload operation.
- No provider/configuration failure is automatically retried, no Restic lock is
  forcibly removed, and no source dump is discarded to recover an upload.
  Existing atomic capture verification and bounded local retention are unchanged.

No systemd service deadline, timer, install manifest, exact restore-verification
logic, R2 storage envelope, policy, database state, or application/UI file changed.
The existing conservative two-environment backup bound is now 3,300 seconds,
still below its unchanged 3,600-second service deadline. The existing narrow
cadence + jitter + dump + upload arithmetic becomes 870 seconds when the local
60-second wait is included, below 900 seconds. Neither arithmetic check proves
live RPO under prolonged contention, provider outages, or other pipeline phases.

## Files

- `infra/vps-foundation/scripts/ac-postgres-backup.py`
- `infra/vps-foundation/scripts/ac-restic-backup-inner`
- `infra/vps-foundation/scripts/ac-restic-restore-check-inner`
- `infra/vps-foundation/scripts/ac-restic-postgres-restore-proof-inner`
- `infra/vps-foundation/scripts/ac-restic-postgres-backup-inner`
- `tests/infra/test_postgres_backup.py`
- `tests/infra/test_postgres_restore_proof.py`
- `tests/infra/test_backup_orchestration_posix.py` (new, stdlib-only proof)

## Verification

Windows focused checks:

```powershell
uv run pytest tests/infra/test_postgres_backup.py tests/infra/test_postgres_restore_proof.py tests/infra/test_backup_orchestration_posix.py -q --tb=short
```

Result: **59 passed, 14 POSIX-specific skips** in 1.42 seconds. Ruff checks and
format checks passed for the changed Python files. Git Bash syntax checks passed
for the four changed shell entry points. `git diff --check` passed.

Local Ubuntu WSL could not start because its registered `ext4.vhdx` is absent;
the local Docker Linux engine is unavailable. Neither service was repaired or
started. The coordinator explicitly authorized an isolated synthetic Linux proof
on the existing host instead.

The proof used a fresh `mktemp` root, `/tmp/ac-alpha-backup-tests.rHqhim`, containing
only five copied repository scripts and the new stdlib-only test. `TMPDIR` was
restricted to that root. No live repository lock, Restic command, Docker command,
database, production configuration, secret, or service restart was used.

```sh
TMPDIR=/tmp/ac-alpha-backup-tests.rHqhim PYTHONDONTWRITEBYTECODE=1 \
  python3 -B tests/infra/test_backup_orchestration_posix.py -v
```

Final result: **7 tests passed, no skips**, in 3.291 seconds. The tests cover:

- actual Python exclusive-lock contention, release/acquisition, and timeout;
- all four exact shell acquisition blocks with shortened test-only durations,
  proving no overlap and a distinct timeout that leaves the owner locked;
- preserved versus closed inherited descriptors;
- a synthetic subprocess producing large sensitive-looking stderr, with only
  the fixed R2 guard failure category exposed.
- an exited upload leader whose descendant ignores TERM and holds stderr open:
  bounded escalation kills only that upload's original process group, and no
  named diagnostic-reader thread remains afterward.

Linux `bash -n` also passed on the copied shell scripts. SHA-256 comparisons
matched all six copied files to the final local files. Key verified hashes:

| File | SHA-256 |
| --- | --- |
| `ac-postgres-backup.py` | `09542b7e28b6fa3cee31f67e7c0f74a7ac4e21360a5c319259d59e1f359b2d3d` |
| `ac-restic-backup-inner` | `2086d65e8db2c937e5835d2bcbbc95530074fb668c8e0a544d2a5261f20a1ef3` |
| `ac-restic-restore-check-inner` | `b29eb3c4ed9706879fb3423b6fdb5e0a6316db04a8373742cb94417e792aa34d` |
| `ac-restic-postgres-restore-proof-inner` | `7c278fb0e8e97822639a67853ac0d8fdcc7404a14f2953d70602320c88e65972` |
| `ac-restic-postgres-backup-inner` | `73ab2280a661fb757387921d5a106c5955bbb859e9f4892775763177c40524e5` |
| `test_backup_orchestration_posix.py` | `bb66c9a15905f6e3fa88060f7e752eed067472a068416bda36d9ebaee716d434` |

After the final rerun and hash match, the exact temporary root's resolved path,
non-symlink status, and current-user ownership were checked before removal. Only
the copied scripts and synthetic test artifacts under that root were removed;
all source files remain in the repository and can recreate the proof. No
production configuration, backup, or evidence was deleted.

## Handoff and remaining gates

Independent infrastructure review through the code-review skill identified one
Important descendant-cleanup gap. The bounded original-process-group escalation
and real POSIX regression above address it. The coordinator re-reviewed the fix
and reported no remaining Critical/Important finding in this scoped diff. The
main lane owns the subsequent exact-reviewed release/install decision. No
repaired script has been activated on the VPS by this work.

Required before declaring backup/restore readiness: reviewed release and managed
installation, actual off-host logical upload with the new safe diagnostics,
successful exact-tag foundation reconstruction, and actual logical restore proof
with the existing provenance/manifest/parity/side-effect checks. Prolonged lock
contention or a remote/provider failure remains a capability-specific blocker,
not permission to weaken verification or manually change database state.
