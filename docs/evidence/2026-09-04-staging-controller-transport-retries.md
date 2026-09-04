# Staging controller transient transport retry evidence

Date: 2026-09-04

## Scope

The trusted Windows staging controller now retries only native SSH/SCP transport
failures (`exit 255`) for read-only release lookup, idempotent private staging
layout creation, exact artifact transfers, and bounded private staging cleanup.
Native stdout and stderr are captured separately so a successful SSH warning
cannot contaminate the exact current-release path used by the idempotent no-op
guard. SCP discovery also happens only after that no-op branch.

The controller deliberately does **not** retry the remote installation command.
Once the backup, migration, reconciliation, or edge-cutover transaction begins,
the existing installer and its rollback contract remain authoritative.

## Failure reproduced

Two exact-SHA deployment attempts for
`a23c93e6acebb7c6a0d31de1c3d5d7374f53be92` stopped before installation because
Cloudflare Access transport establishment timed out. The first failed during the
read-only current-release lookup. The second reached the SCP transfer and failed
before the installer ran. Public staging health remained on release
`65ea3e1094ae462c071a70ef2463f5a8c7754196`.

## Verification

```text
python -m pytest tests/infra/test_staging_controller.py -q
5 passed

$env:PYTHONPATH='packages/python'; python -m pytest tests/infra -q
157 passed, 10 skipped

PowerShell parser validation
POWERSHELL_PARSE_OK

Behavioral stdout/stderr separation probe
STDOUT_STDERR_SEPARATION_OK

git diff --check
passed
```

The skipped checks are the repository's documented Docker/POSIX/opt-in restore
drill cases; none are introduced by this change.
