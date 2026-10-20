# Dev-live API and idle Lead Desk AI runner — 20 October 2026

Assignment: [AUT-2158](/AUT/issues/AUT-2158). Named host operator authority:
[AUT-63](/AUT/issues/AUT-63). Run `13dd2d42-66fb-4462-b23a-163781f88813`.
Implementation commit: `220056a3` on the shared `dev/live` workbench.

The API now runs two Uvicorn server workers at Nice=0 on loopback port 8101.
The existing background Sales Xray worker remains Nice=10, with its original PID
and no restart. Lead Desk AI is enabled as a systemd service but remains switched
off in Admin. Its journal confirms `started: lead-desk-ai` followed by
`stopped: lead_desk_ai_off`; no model execution or message was triggered.

## Files and live verification

| Repository source | Installed path |
| --- | --- |
| `infra/application/development/ac-dev-live-api.service.d/zz-concurrency.conf` | `/etc/systemd/system/ac-dev-live-api.service.d/zz-concurrency.conf` |
| `infra/application/scripts/ac-lead-desk-ai` | `/usr/local/sbin/ac-lead-desk-ai` |
| `infra/application/systemd/ac-lead-desk-ai@.service` | `/etc/systemd/system/ac-lead-desk-ai@.service` |

The new API drop-in sets `WEB_CONCURRENCY=2`, `Nice=0`, and `CPUQuota=200%`.
The installed Uvicorn reads this environment setting through the existing package
runner. It keeps the package's compatible event-loop factory and survives the
automatic deploy's rewriting of `slot.conf`. MemoryMax remains 768 MiB; observed
API memory was approximately 376 MiB after startup.

Read-back: API supervisor PID 3189769, server worker PIDs 3189797 and 3189798,
all Nice=0. Background worker PID 2861849 remains Nice=10. Lead Desk runner PID
3190213, Nice=10, active/running, NRestarts=0. Readiness HTTP 200, status `ready`,
application release `203cba2bedbe29247bbf3c49ade77e069a23321d` unchanged.
All installed file bytes match repository sources.

## Timing evidence and limits

`scripts/dev/benchmark-dev-live-api.py` logs in with the existing synthetic QA
account, performs one warm-up and three single list reads, then three bursts of
eight concurrent requests. Destination: `127.0.0.1:8101`, public dev Host header,
`/v1/conversation/acquisition/submissions?include_owners=true`. All measured reads
returned HTTP 200. Credentials, cookies and response contents are never printed.

| Sample (UTC) | Median single read | Median eight-request completion |
| --- | ---: | ---: |
| Before, 08:59:15 | 32.46 ms | 174.13 ms |
| Initial after, 09:00:23 | 86.70 ms | 279.73 ms |
| Warmed follow-up, 09:01:08 | 87.62 ms | 208.56 ms |

These small-account API measurements show no speed improvement. They do not
measure browser rendering or reproduce the owner's populated account and the
approximately 1.2-second page-request bursts described in the assignment. Both
post-change samples are retained, including the slower initial sample. No claim
that the owner's page-load latency improved is established by these receipts.

## Checks and rollback

- Root authorization, installer dry-run and apply: exit 0.
- Existing focused runner and HTTP-runner tests: **5 passed**.
- Installer Bash syntax, benchmark Ruff check/format, API import and systemd unit
  verification: passed.
- The dry-run reads the existing Admin switch and refuses installation unless it
  is disabled. The installer never edits that switch or supplies provider keys.
- Installer: `infra/application/development/install-dev-live-runners.sh`; dry-run
  by default, `--apply` changes only the three dev destinations above. It locks
  against automatic backend deployment, backs up prior files and service state,
  checks readiness and automatically restores on failure.
- Explicit rollback, through the authorized Root run:
  `sudo -n /usr/local/sbin/ac-root run -- bash /home/acdev/src/dev-live/authority-closers-platform/infra/application/development/install-dev-live-runners.sh --rollback /var/lib/ac-dev-live-runners/AUT-2158/20261020T085939Z-3189556`.
  This restores the old API settings and removes the previously absent runner
  unit, executable and concurrency drop-in. No rollback was needed.

The referenced laptop-only `lead-desk-ai-root-steps-20261020.md` was unavailable
on this host. The checked-in wrapper, CLI, unit and existing fictional tests
were verified locally instead. The wrapper uses the same Infisical launch as
`ac-call-data`. No staging/production operation, release, manual database change,
Admin change, secret change or external account change occurred.

Raw safe receipts are retained under `/home/acdev/strikes/2158/evidence/` and
uploaded to the task. Other agents' working changes were preserved.
