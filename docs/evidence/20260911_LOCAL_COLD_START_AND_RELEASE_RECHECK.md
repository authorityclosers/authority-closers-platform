# Local cold-start and release recheck (2026-09-11)

## Bounded local launcher correction

The 60-second launcher deadline repeatedly stopped Admin while webpack was still
compiling. The latest failed attempt logged no dependency-file error. Ten direct
Node reads of the previously failing zod file succeeded; this does not establish
the cause of the earlier transient filesystem error.

The readiness deadline is now 180 seconds. Ownership checks, loopback binding,
anonymous API status/cache/cookie checks, and selected-process-only cleanup are
unchanged. No dependency reinstall, host-file change, port proxy, or remote write
was used for this correction.

Admin and Coach then completed the managed launcher checks. Independent local
login probes returned 200 on ports 3101 and 3102. Learner port 3100 was unavailable
at this checkpoint and still needs its managed restart; the launcher's printed
list of all three URLs is not evidence that all three are running.

Offline tests initially exposed an outdated reuse-branch fixture: it omitted the
anonymous API helper and used PSCustomObjects instead of the launcher's actual
hashtables. The fixture now models both successful probes and probe rejection.
The six reuse-branch tests passed after correction. The earlier broader run had
30 passing tests with two fixture failures; a fresh full rerun remains required.
Ruff passed before the final fixture-type correction. No full-release validation
or deployment is claimed by these focused tests.

## Read-only live checkpoint

At approximately 10:12 IST, staging API readiness reported release
`8474c9824fdfdbc41730df52c3e7a1119473d2a1`. This supersedes earlier observations of
`4e8d413` or `4a975bf`; this task did not perform that external deployment.

- Learner and Coach staging login documents: HTTP 200.
- Admin staging and production login: HTTP 302 to the access boundary.
- Learner and Coach production login: HTTP 503.
- WordPress apex: HTTP 200; no WordPress changes made.
- Latest-UI PR 47 remains open/conflicting at `cb8df7b`.

Reachable login documents do not prove authenticated workflows, current UI
acceptance, video playback, or completion of the requested production release.
