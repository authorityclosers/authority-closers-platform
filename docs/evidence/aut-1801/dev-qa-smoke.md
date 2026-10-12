# AUT-1801: bounded dev Report/Coaching proof

The existing known-clip QA smoke now accepts `--environment development` at
`https://salesxray-dev.authorityclosers.com`. It is limited to the synthetic
dev-live QA identity documented by the devlive-backend operator
(`devlive-qa+20261011@example.com`). Credentials stay runtime-injected in the
operator's held session; no credential files or values belong in this handoff.

Browser QA runs the existing `scripts/sales-xray-account-smoke.py` through
`ac-heavy` with `--environment development --browser` after the approved dev
worker and intended committed source are serving. Pin the worker/tool source,
serving API release and dev approval separately in the private receipt. The
script keeps a metadata-only result: exact submission/recording/digest,
Report/per-call Coaching bindings, elapsed time and optional browser visibility.

Origin and QA-identity checks run before any credential send. Dev explicitly
selects the edge's live backend cookie before login, including when the edge
temporarily defaults to staging; an unavailable live API fails the smoke.
The smoke uploads
the committed fictional clip once; it never retries a held/uncertain provider
send and refuses quotes above the existing cap. It then verifies the final report
and Coaching against the original source, person, tenant and report revision.
This short fixture proves the journey; it does not prove the 20-minute latency
target or independent report quality. Staging/production remain frozen.
