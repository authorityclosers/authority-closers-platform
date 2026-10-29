# Release train smoke

The orchestrator must first ship `scripts/ops/ac_smoke.py` to main through the
normal release path. Adding it to dev alone does not repair train runs: the
engine extracts scripts/ops from the main source archive. No installed engine
or timer change is required.

The standalone Python 3 script checks staging or production over public HTTPS:
learner home and health, coach login, Sales Xray home and health, API live and
ready, anonymous programs, and private docs/schema returning 404. Redirects
fail. Each request has an 8,000 ms limit and the process has a 110-second alarm.
Only statuses, timings and fixed failure codes enter evidence; response bodies,
headers and exception text are suppressed. The optional signed-in fixture
analysis is deliberately omitted: existing canaries retain that deeper check
and its provider budget. This smoke creates no accounts, calls or analyses and
reads no credentials (including reference-ac-qa-smoke-accounts).

Each invocation atomically replaces
`<state-dir>/<environment>/<core>-<web>.json` with fresh pass/fail evidence.
Its digest is SHA-256 of compact sorted JSON excluding the digest key, prefixed
`sha256:`. Pass exits 0; failure and timeout exit 1. A write failure exits 1.
The engine validates the exact pair, digest and freshness and archives evidence
by digest before using it. A pass is evidence of public HTTP availability, not
a browser rendering or paid AI analysis check.

Under [ADR 0041](../adr/0041-release-train-standing-approval.md), eligible green
patches can then promote automatically using the same CI artifacts after
staging smoke, migration classification, verified backup/restore evidence and
all existing engine guards. Production smoke follows promotion. Failed smoke
pauses production and triggers the engine's permitted rollback; core rollback
cannot cross a migration head. Existing pauses and failed-pair marks remain
operator decisions; this script does not clear them.

Minor and major versions still need the orchestrator's supervised release path
and owner confirmation. Destructive/unknown migrations and supervised recovery
also remain outside standing patch approval. Builders do not deploy, change
timers or manually edit staging/production.
