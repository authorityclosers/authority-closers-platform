# Heavy execution port, version 1

This interface separates queue selection from execution. It adds no schema,
provider permission, unreviewed reanalysis producer or business priority inference.

| Topic | Priority | Existing adapter / required activation |
| --- | --- | --- |
| ac.interactive.v1 | immediate | Existing API/core email and hosted analysis workers retain their exact allowlists |
| ac.background.v1 | low | Container for separately admitted background topics, gated before claiming |
| ac.heavy.transcode.v1 | low | Existing durable `media.process_version.v1` rows and StudioVideoJobWorker |
| ac.heavy.scan.v1 | low | Reserved queue adapter; current synchronous scan uses private forwarded clamd socket |
| ac.heavy.reanalyse.v1 | low | Reserved adapter; requires explicit source generation, owner request and original provider gates |
| ac.heavy.export.v1 | low | Reserved adapter; requires existing export authorization |
| ac.heavy.backup.v1 | low | Reserved adapter; backup-streaming job owns schedule and receipts |

`DurableTopicConsumer.run_once()` resolves zero or one exact-topic job and returns
its claim count **after** its durable outcome. The adapter owns claim/lease tokens,
recovery generation, deadline, retry, idempotency and terminal outcome. Returning
one is a count, never a clean scan or business-success assertion. Unknown topics
are refused. A queue must never hand an interactive row to a background consumer.
`priority_once` checks the interactive consumer first, and claims background only
when interactive is empty and the load gate is green. Existing queues are not
relabeled or rewritten by this interface.

The supplied executable is deliberately limited to the existing Studio adapter:

```sh
nice -n 10 python -m ac_platform.worker.heavy_lane \
  --topic ac.heavy.transcode.v1 --max-jobs 100 \
  --credit-file /run/ac-capacity/credits.json
```

Run only through the release-owned heavy host/container service and `heavy.slice`
(or Docker `cgroup_parent: heavy.slice`, `cpu_shares: 10`). Use the exact reviewed
application image and production-scoped credentials, object and scratch mounts;
never inherit a developer shell's environment. `AC_MEDIA_FILESYSTEM_ENABLED=true`
is required on this dedicated runner, while the lean core worker sets it false.
The runner calls the original StudioVideoJobWorker: its leases, retries, deadlines,
recovery fence and provider budgets remain intact. SIGTERM stops admissions and
finishes accepted work. Task cancellation also drains accepted work. A successful
exit after N claimed jobs allows the supervisor to recycle the process; retry and
failure jobs count too. Hosted analysis also drains its already in-flight stages,
so it can finish up to N + provider_consumers stages at recycle time.

The gate uses one-minute load / 2 CPUs (red at >=0.75 per CPU), interval CPU steal
(red at >=10%), and an optional atomic JSON observation:

```json
{"balance_percent": 75.0, "observed_at": 1793214000.0}
```

`observed_at` is UTC epoch seconds; balance <30%, age >180 seconds, a future timestamp,
missing/malformed configured file or unavailable CPU counters means wait. No AWS
request is made. The first sample primes CPU deltas and waits five seconds. Gates
run before claims and never revoke a lease or extend a deadline. Interactive work
bypasses background admission. The credit exporter and alerts belong to operations.

A remote runner receives only admitted durable job identifiers and production
object references, tenant/generation, immutable source checksum/version, requested
operation, idempotency key and deadline. It must resolve these through the existing
service authority, never execute a caller-supplied path or command. Use private,
authenticated encrypted transport. The same-host cgroup is an interim execution
target, not permission to exceed the 4 GiB physical budget or send real calls to dev.
No remote queue transport or production provider is activated by this change.

The existing ClamAV INSTREAM adapter streams to a forwarded Unix socket: no local
scanner process is required. It binds the verdict to checksum and unchanged object
metadata; it rejects missing/truncated/contradictory replies, errors and scan-limit
outcomes. No acknowledgement, timeout or absent adapter may generate `clean=true`.
The scan queue adapter must preserve this rule before it is activated. Scanner
signatures, policy and private forward health remain prerequisites.
