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
with the router at 172.18.0.2 also required recovery; this leaf now contains a
fail-closed reconciliation action for the one reviewed learner occupant. It
does not change or recreate the current Docker network.

`infra/application/scripts/recover-sales-xray-startup.py` renders the native
consumer unit, the edge reconciliation unit, and a combined descriptor. It
provides two bounded recovery actions:

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
6. For the router collision, discover only `/ac-edge-router` and the exact
   reviewed `ac-application-{environment}-learner-web-1` identity. Stop that
   immutable learner ID, start the edge ID, then start the learner ID and require
   it to receive a different address. Unknown labels, services, occupants,
   address ranges, or replacement IDs refuse without mutation. Every failure
   after the stop attempts to restore the exact learner ID; if the edge had
   started, it is stopped first so the original topology can be retried.

The systemd units point to an exact versioned application release path. The
source-owned `install-sales-xray-startup-recovery.py` consumes the combined
descriptor, verifies its SHA-256 and exact unit content, refuses unit drift,
and atomically writes only missing units. It runs `daemon-reload` and enables
the exact units only with `--execute`; `--activate` is an additional explicit
request to use `enable --now`. A root operator can use this path after the
immutable release is installed:

```sh
release=<40-lowercase-hex-release>
python3 /srv/authority-closers/application/releases/$release/scripts/recover-sales-xray-startup.py \
  --environment production --render-descriptor --release-sha "$release" \
  >/var/tmp/ac-sales-xray-startup-production-$release.json
descriptor_sha=$(sha256sum /var/tmp/ac-sales-xray-startup-production-$release.json | awk '{print $1}')
python3 /srv/authority-closers/application/releases/$release/scripts/install-sales-xray-startup-recovery.py \
  --environment production --release-sha "$release" \
  --descriptor /var/tmp/ac-sales-xray-startup-production-$release.json \
  --descriptor-sha "$descriptor_sha" --execute --activate
systemctl is-enabled --quiet ac-sales-xray-edge-reconcile-production.service
systemctl is-active --quiet ac-sales-xray-edge-reconcile-production.service
systemctl is-enabled --quiet ac-sales-xray-startup-production.service
```

Run the same sequence for staging before production. The root release
coordinator owns installation, immutable image checks, rollback, and live
readback. Starting a worker may resume already-authorized jobs; this action is
not a claim of zero indirect inference.

The current `ac_edge` network remains the reviewed `172.18.0.0/16` range with
the router at `172.18.0.2`. A future candidate range is recorded in
`infra/vps-foundation/config/release/future-network-transition.yaml`; it is
inactive documentation only. Migration requires a new reviewed release,
quiescence, backup, cutover, and rollback rehearsal. No current network
recreation is permitted by this leaf.

## Validation

Run from the isolated worktree using the existing Python environment:

```powershell
$env:PYTHONPATH='D:/Projects/authority-closers-xray-boot-recovery-20260915/packages/python'
& 'D:/Projects/authority-closers-v02-consolidation/.venv/Scripts/python.exe' -m pytest tests/infra/test_sales_xray_startup_recovery.py --basetemp D:/AC-authority-closers-release-audit/peer-boot-recovery-final-20260915 --junitxml D:/AC-authority-closers-release-audit/peer-boot-recovery-final-20260915.xml -q
```

The final receipt records 41 passing cases covering both environments, the actual
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
