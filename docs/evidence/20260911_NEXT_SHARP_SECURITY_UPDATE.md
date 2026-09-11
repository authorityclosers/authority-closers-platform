# Next and sharp security dependency update evidence

Date: 2026-09-11

## Scope

This change coordinates the minimum patched runtime versions required by the
open repository advisories:

- Next.js `16.3.3` for `GHSA-2xp9-vwfh-vxw4` and
  `GHSA-p293-qw3h-jr36` / `CVE-2026-75604`.
- sharp `0.35.4` for `GHSA-rgj7-g3m4-5g8c`.
- `eslint-config-next` and the `@ac/operations-web` Next peer are kept on
  the same exact Next version.

The three web-app manifests, operations peer, workspace sharp override, and
lockfile are updated together. No advisory was dismissed based on its
default-branch location.

## Immutable package review

Next `16.3.3` was captured with bundled Node `24.19.0` using
`npm pack next@16.3.3`.

- npm integrity:
  `sha512-tuRTx1nQ/yVw83cwJBo9F+njGUgMn3UHQycreWHB8XsStvvAh1AthbI8/4IpKnFaF58F+iSiHejYOlMQ/eq83g==`
- archive SHA-256:
  `810e48c5154598ce5602eb789ca4ce43070210d91a08cdfd741f9e094e863b39`
- the npm integrity exactly matches the regenerated lockfile
- `dist/trace/trace.js` still reads
  `NEXT_TRACE_SPAN_THRESHOLD_MS` before framework configuration and records
  only durations greater than the configured millisecond threshold
- `Span.stop` still rejects durations above `Number.MAX_SAFE_INTEGER`
- `next/experimental/testing/server` still exports
  `unstable_doesMiddlewareMatch`

Therefore the existing pre-bootstrap trace privacy contract remains valid:
the child-only value `9007199254740991` milliseconds is above every accepted
span duration. The exact-version checks in the launcher, Next configuration,
and installed-runtime test now require `16.3.3`; the guard itself is not
weakened or bypassed.

sharp `0.35.4` was also captured immutably.

- npm integrity:
  `sha512-n++8XWcj+jCOr2IOl7h8LbKnGBDY4aPbmprMONBNFdn0ImXqpGVv5zliDs0V9HbmbCQLpbuo2ej9rAoOQTvMDA==`
- archive SHA-256:
  `6ebef10290372c7309d9e22e3ecb9e32ca6a3aa6e07f3d83aa904df8ae4f6a5a`
- the npm integrity exactly matches the regenerated lockfile

## Validation

The lock was regenerated with bundled Node `24.19.0` and pnpm `11.19.0`
using `pnpm install --lockfile-only --ignore-scripts`.

- frozen offline lock-only validation: passed
- pnpm production audit at high severity: no known vulnerabilities found
- old `next@16.2.11` and `sharp@0.35.0` lock entries: absent
- immutable Next `16.3.3` trace negative control: 221 synthetic URL markers,
  48,595 trace bytes
- immutable Next `16.3.3` guarded control: 0 markers, 0 trace bytes
- dependency security regression asserts all manifest pins, the operations
  peer, sharp override, patched lock entries, and absence of the vulnerable
  lock entries
- coordinated forced frozen installation under bundled Node `24.19.0`:
  passed, with all managed UI processes stopped
- installed resolution in learner, admin, and coach:
  Next `16.3.3`, sharp `0.35.4`
- focused learner dependency, trace-privacy, and local-upstream tests:
  3 files, 16 tests passed
- focused coach proxy/upload-routing test: 1 file, 24 tests passed
- learner TypeScript: passed
- admin TypeScript: passed
- coach TypeScript: passed
- learner full suite: 81 files, 1,504 tests passed
- admin full suite: 27 files, 634 tests passed
- coach full suite: 2 files, 38 tests passed
- total full suites: 110 files, 2,176 tests passed
- changed learner and coach source tests/configuration ESLint with
  `--max-warnings 0`: passed

The full Vitest suites used `--maxWorkers=1` after a default-concurrency
learner attempt encountered Windows filesystem `lstat` errors while starting
workers. That incomplete attempt is not counted above; the serialized rerun
completed without worker errors or assertion failures. This change does not
restart the managed UI processes.
