# Practice progress: bounded database reads

The local practice progress application now performs **11 SELECTs for either one or twenty recent attempts**, including its own fresh person/session/tenant/membership admission, saved profile, balance, day-count and award reads. This is a measured service query count, not a browser latency claim or a count of the enclosing HTTP authentication dependency's separate work.

Only `PracticeApplication.progress` production logic changed. Recent versions are loaded in one tenant-scoped batch and still checked against their saved content digest. One grouped query counts acknowledgments of each item's **latest** response; it does not count stale older feedback and does not retrieve private answer or feedback JSON. Attempt/award ordering, the twenty-attempt/fifty-award limits, exact response fields, persisted policy, receipts and calendar semantics are unchanged. No schema or reward mutation logic changed.

Validation:

- 35 practice engine tests passed in 12.43 seconds. New regressions measure exactly eleven SELECTs for one and twenty attempts, compare every summary field with the full single-attempt projection, retain reward/day totals, reject a corrupted cached content snapshot, and preserve latest-only counts even with deliberately inconsistent historical acknowledgments in a disposable fixture.
- The existing twenty PostgreSQL tests passed again against the optimized application in 18.64 seconds. Fresh random test schemas covered real migration integrity, immutable history, deferred journal checks, concurrency, rollback and timezone rollover; the running sandbox was not migrated or restarted by this subtask.
- Scoped Ruff and strict mypy passed. Parent independently reviewed joins, tenant/person filters, ordering, content-integrity and acknowledgment semantics and reported no Critical/Important findings.

Activation remains parent-owned after the browser QA agent reports a safe restart boundary. No deployment, external state change, performance percentile or public-release acceptance is claimed here.
