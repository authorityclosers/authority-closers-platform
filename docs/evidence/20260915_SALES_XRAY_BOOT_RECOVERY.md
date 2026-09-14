# Sales Xray: recover the observed reboot startup failure

This leaf is separate from the frozen b4ebfcf5 release. It is implemented and
locally tested, **not installed or boot-tested on the VPS**. It must not delay
the already-tested application release or be represented as live protection.

On 14 September 2026 at approximately 18:34 UTC, the application tunnel lost its
connections. This leaf does not establish why the VPS became unresponsive.
After the release coordinator restarted it, Docker had already attempted to
start both environments' API and Sales Xray worker containers before systemd
created their native socket directories. Those four containers exited 127.
The coordinator supplied the retained error:

```text
failed to create task for container: failed to create shim task: OCI runtime create failed: runc create failed: unable to start container process: error during container init: failed to fulfil mount request: open /run/ac-sales-xray/production: no such file or directory
```

The existing `ac-sales-xray-native-{environment}.service` was enabled and active
by the time of inspection. It correctly owns the root:10001 mode-0750 runtime
directory through `RuntimeDirectory`. The problem was startup timing, not a
missing provider credential. The coordinator restarted the existing containers
after those directories appeared. A separate dynamic Docker address collision
with the router at 172.18.0.2 also required recovery; this leaf does not change
the network or solve that IP allocation issue.

`infra/application/scripts/recover-sales-xray-startup.py` renders an additional
systemd unit for one environment and provides its bounded recovery action:

1. Order the companion unit after Docker and that environment's native helper.
   Requiring the native helper before Docker itself would create a cycle.
2. Wait at most 30 seconds for the trusted native socket and directory metadata.
3. Inspect only the two exact existing Compose containers, using selected Docker
   metadata fields. No container environment or credential values are read.
4. Retry only the observed exit-127 mount failure for that environment's exact
   runtime directory. Running containers, intentional stops, disabled restart
   policies, OOM exits, other errors and other Compose identities are untouched.
5. Recheck the same immutable container ID immediately before starting it and
   require matching running-state readback. Never recreate a container or change
   its image, approval, database, network, provider configuration or quota.

The systemd unit points to an exact versioned application release path. Rendering
the unit does not install it. Source-owned release installation and rollback
integration remain necessary before enabling it. Starting a worker may resume
already-authorized jobs; this action is not a claim of zero indirect inference.

## Validation

Run from the isolated worktree using the existing Python environment:

```powershell
$env:PYTHONPATH='D:/Projects/authority-closers-xray-boot-recovery-20260915/packages/python'
& 'D:/Projects/authority-closers-v02-consolidation/.venv/Scripts/python.exe' -m pytest tests/infra/test_sales_xray_startup_recovery.py --basetemp D:/AC-authority-closers-release-audit/peer-boot-recovery-final-20260915 --junitxml D:/AC-authority-closers-release-audit/peer-boot-recovery-final-20260915.xml -q
```

The final receipt records 30 passing cases covering both environments, the actual
boot error, refusal of unrelated failures and wrong identities, container-state
races, immutable-ID readback, socket disappearance/timeout, unsafe filesystem
metadata, unit ordering, and release-path injection. Ruff lint/format and
`git diff --check` pass. These are deterministic tests with simulated Docker and
filesystem state. No VPS reboot, runtime mutation, provider call, secret read or
production database action is performed by these tests.

External incident evidence:
`D:/AC-authority-closers-release-audit/peer-browser-outage-scope-20260914-1839.json`.
The application pages showed Cloudflare 1033 while the existing apex site rendered.
Later Chrome verification showed Sales Xray rendering again after recovery; that
restoration is not evidence that this new companion unit has been deployed.
