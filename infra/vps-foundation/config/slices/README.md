# Host slices: production keeps priority on ac

On 28 Oct 2026 at 13:21Z four agent jobs started at once with no limits. Memory and the 4 GiB
swap ran out, the kernel reclaimed production's pages, and the production API's reads waited up
to 60 s (owner bug #67; `/home/acdev/scratch/leads-speed-20261029/REPORT.md`, part 2). The
orchestrator applied these limits live on 29 Oct 03:48Z with `systemctl set-property`
(`/var/log/ac-ship.log`). These files are the same settings, kept in Git.

| File | Applies to | Setting |
|---|---|---|
| `user-1002.slice.d/90-ac-dev-cap.conf` | acdev (uid 1002): dev servers, workbench, dev-live | `MemoryHigh=5G`, `CPUWeight=25` |
| `ac-strikes.slice.d/90-swap-cap.conf` | agent jobs in `ac-strikes.slice` (at most two at once) | `MemorySwapMax=1G` |

`ac-strikes.slice` itself (CPUQuota 120%, CPUWeight 50, MemoryHigh 6G, MemoryMax 8G) is on the
host in `/etc/systemd/system/ac-strikes.slice`. Agent jobs go in it: `systemd-run
--slice=ac-strikes.slice ...`. The containers' side (memory reservation, CPU shares, OOM order
for the production API, PostgreSQL and web) ships with the application release:
`infra/application/compose.production-metrics.yaml` and `infra/sales-xray-web/environments/production.env`.

## Install (root on ac)

```bash
id -u acdev   # must print 1002; otherwise rename the user-<uid>.slice.d folder
install -D -m 0644 -o root -g root user-1002.slice.d/90-ac-dev-cap.conf \
  /etc/systemd/system/user-1002.slice.d/90-ac-dev-cap.conf
install -D -m 0644 -o root -g root ac-strikes.slice.d/90-swap-cap.conf \
  /etc/systemd/system/ac-strikes.slice.d/90-swap-cap.conf
# The live set-property copies take precedence over /etc/systemd/system; remove them once
# these files are in place, so there is one source.
rm -f /etc/systemd/system.control/user-1002.slice.d/50-MemoryHigh.conf \
  /etc/systemd/system.control/user-1002.slice.d/50-CPUWeight.conf \
  /etc/systemd/system.control/ac-strikes.slice.d/50-MemorySwapMax.conf
systemctl daemon-reload
systemctl show user-1002.slice -p MemoryHigh -p CPUWeight
systemctl show ac-strikes.slice -p MemorySwapMax
logger -t ac-ship "host slices from infra/vps-foundation/config/slices installed"
```

Expect `MemoryHigh=5368709120`, `CPUWeight=25` and `MemorySwapMax=1073741824`. Watch the `high`
and `max` counts in `/sys/fs/cgroup/user.slice/user-1002.slice/memory.events` for a day before
tightening.
