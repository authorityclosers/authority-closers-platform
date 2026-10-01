# Dev-host web timeout diagnosis — 1 October 2026

Assignment: [AUT-701](/AUT/issues/AUT-701); [approved D1 plan](/AUT/issues/AUT-699#document-plan).
Evidence only. No app, test, configuration, workflow, timeout default or worker default changed.

## Source and runtime

- Gate-selected source: `1e2c8e729bdefda8d7cdc165bcfad0e7d25db0dd` on `task/devenv/701-web-timeout-diagnosis`; clean before diagnostics and before/after every completed cell.
- Gate status reported devenv FREE and main running; `start` admitted the lane under the constitution’s running-main rule, and subsequent `check` passed.
- Node `v24.19.0`, pnpm `11.19.0`, installed Vitest `4.1.11`, happy-dom `20.14.0`, React/React DOM `19.2.8`; no dependency install.
- Lockfile SHA-256: `c767a3247e187a89d249abf6e2a24bff0bfac0ede4d3b5033c2785ffcc022e70`.
- Scoped diff from `ef0e953c6105f4dc5a5c3dc3074182fd3e960cb8`: package/lock remove `qrcode.react@4.2.0` and `jsqr@1.4.0` (22 deleted lines); all eight other scoped files unchanged.
- Installed CLI help and `createVitest` resolved config confirm test timeout 5000 ms, hook timeout 10000 ms, `forks`, isolation true; CLI file parallelism defaults true, retry 0; no committed overrides.
- Node `os.availableParallelism()` = 1, logical/affinity CPUs = 4. Installed CLI `resolveMaxWorkers` uses `max(availableParallelism()-1,1)` in run mode; default ceiling and explicit `--maxWorkers=1` both resolve to 1.
- This is the 5000 ms timeout baseline on the current pinned source; dependency drift prevents claiming an identical historical environment.

## Fixed-variable matrix

Commands were sequential from the repository root, with unchanged dependencies/pool/isolation/fake timers/assertions.
F = `pnpm --filter @ac/sales-xray-web exec vitest run app/acquisition-studio.test.tsx`; P = `pnpm --filter @ac/sales-xray-web test`.
Each child used `timeout --signal=TERM --kill-after=2s 480s`; total matrix budget 1200 s. The wrapper samples metrics every 5 s.
FWT is descriptive only. The one permitted package pair was admitted because one selected file and a default one-worker ceiling make FW uninformative.

| Cell / only added options | UTC start → end | Raw exit | Files / tests | Wall s | Vitest / test-body s |
| --- | --- | --- | --- | --- | --- |
| F0: unchanged | 10:58:10.743 → 10:59:16.266 | 0 | Test Files  1 passed (1) / Tests  108 passed (108) | 65.521 | 62.20 / 53.99 |
| FW: `--maxWorkers=1` | 10:59:16.519 → 11:00:30.266 | 0 | Test Files  1 passed (1) / Tests  108 passed (108) | 73.746 | 70.72 / 62.28 |
| FT: `--testTimeout=15000` | 11:00:30.530 → 11:01:40.567 | 0 | Test Files  1 passed (1) / Tests  108 passed (108) | 70.034 | 66.97 / 56.69 |
| FWT: `--maxWorkers=1 --testTimeout=15000` | 11:01:40.826 → 11:02:44.566 | 0 | Test Files  1 passed (1) / Tests  108 passed (108) | 63.738 | 60.80 / 52.98 |
| P0: unchanged | 11:02:44.756 → 11:07:23.084 | 0 | Test Files  101 passed \| 1 skipped (102) / Tests  975 passed \| 6 skipped (981) | 278.327 | 276.42 / 118.74 |
| PW: `--maxWorkers=1` | 11:07:23.186 → 11:11:27.470 | 0 | Test Files  101 passed \| 1 skipped (102) / Tests  975 passed \| 6 skipped (981) | 244.283 | 242.68 / 100.61 |

Raw exit semantics: 0 = completed pass; a test failure’s raw nonzero exit is retained; 124 = external cap/censored; 143 = returned SIGTERM; negative subprocess returns identify signals. No retries.
The unchanged reporter emits aggregate file/test durations, not per-case durations or passing case labels. Per-case timings are **unavailable for every passing case**; no reporter flag or instrumentation was added. Source case names/templates are retained in the raw archive; runtime counts above are reporter counts.

## Read-only host and cgroup observations

`/proc/loadavg`/getloadavg, `/proc/meminfo`, host PSI and the current unified cgroup CPU/memory counters were sampled before, during and after each cell; the archive retains every UTC sampling time.
CPU quota `cpu.max=100000 100000` (1 CPU); memory limit `3221225472` bytes (3 GiB). Counters describe the shared cgroup, not this test process alone.

| Cell / samples | Load1 range | Available GiB range | Host CPU PSI some avg10 % | Cgroup CPU throttled periods / usec delta | Cgroup OOM / OOM-kill delta |
| --- | --- | --- | --- | --- | --- |
| F0 / 16 | 2.48–4.08 | 9.40–10.31 | 37.76–55.93 | 655 / 97795610 | 0 / 0 |
| FW / 17 | 2.56–3.68 | 9.32–10.14 | 41.54–56.49 | 732 / 103470486 | 0 / 0 |
| FT / 16 | 1.84–2.76 | 9.43–10.37 | 38.71–54.54 | 700 / 96362314 | 0 / 0 |
| FWT / 15 | 1.09–1.77 | 9.53–10.42 | 39.61–54.70 | 636 / 85560550 | 0 / 0 |
| P0 / 58 | 0.91–5.67 | 9.52–10.41 | 31.87–69.96 | 2772 / 330874941 | 0 / 0 |
| PW / 51 | 1.48–5.24 | 9.60–10.38 | 28.79–54.14 | 2421 / 288743623 | 0 / 0 |

All requested host/cgroup metric files were available. No environment values, process command lines, artificial load, unrelated process control or service changes were used. Natural concurrent work was not controlled or independently attributed.
CPU PSI and quota throttling establish runtime pressure during these observations; their presence during passing cells does not establish the cause of past timeouts. Memory/pressure samples and event counters are observational, not a per-test resource attribution.

## Preserved acquisition phases

The scoped test/helper blobs match ef0e953. The following named cases remain unchanged and are included in each completed 108-case focused pass:

- `waits for native file checks after navigating away mid-upload, then starts once across remounts`: “Checking recording”, zero quotes before/after the saved-call remount, fake advance exactly 3000 ms, then one quote and one acceptance and accepted state across remounts (test lines 925–957).
- `reconciles a lost root-owned acceptance with the owner plan and never posts it again`: synthetic 503, one quote, one acceptance POST, owner-plan GET and accepted state (959–981).
- Older `keeps one source upload alive across client navigation and shows the confirmed result` and `uses one upload consent, auto-accepts the same call's quote, then shows the report` remain unchanged (728, 1069); one source PUT / quote / acceptance assertions stay intact.
- `button()` still asserts the requested text exists; “Analyse my call” missing-button diagnostics remain intact. `flush` drains 15 microtasks inside React act; `settleAll` repeats six times (110, 115, 278). No missing await is demonstrated.

## Classification and next question

**Not reproduced on this pinned source:** all four focused cells pass 108/108; both package cells pass 975 with the same six skips. No test assertion/async-sequence failure, “Analyse my call” missing-button failure, timeout, cap expiry or signal termination occurred, so there is no first failing test phase to identify.

**Cause remains inconclusive:** the default worker ceiling already equals one; the package pair does not isolate multiworker contention. The shorter final package wall time (244.283 versus 278.327 s) cannot establish a worker effect, and sequential cache/runtime variation is uncontrolled. Shared CPU pressure/throttling coexists with passing runs; no OOM or OOM-kill counter increased.

Both package logs include an `AggregateError` for `ECONNREFUSED` at localhost:3000 (IPv4/IPv6). Each still exits 0 with all non-skipped tests passing; this output is retained and is not classified as an assertion failure or a diagnosed cause.

Narrow next question for the parent plan: did the historical failing runs have an effective worker ceiling greater than one under the same source/dependency/cgroup limits? Recover that runtime/termination receipt before authorizing a controlled follow-up. No repair, CI change, extra repetition or resource change is supported by this receipt.

Repeat on dev: use the dedicated gate-selected clean devenv checkout and existing frozen installation; verify the pinned runtime/defaults, execute the six commands above sequentially, cap each child at eight minutes and the matrix at twenty, and sample the same metrics. Do not change assertions, fake timers, pool, isolation, defaults, services or natural workload. No browser/deployed behavior changes are involved.

Delivery remains subject to existing CI, CTO review, CEO approval and watchdog merge; no merge or deployment was performed by this diagnosis.

Raw evidence: `AUT-701-raw-receipts.zip` on [AUT-701](/AUT/issues/AUT-701), with six unedited logs, exact commands/exits, 5-second UTC metrics, source hashes/case-label templates, dependency receipts, installed options/worker resolution and the run-owned measurement wrapper.
Archive SHA-256: `82686f2f907d8b6328d86b22a705a7895003204e7327c08d3352675ec91cec70`. Installed dependency metadata and every scoped source hash remained unchanged after all six invocations.
