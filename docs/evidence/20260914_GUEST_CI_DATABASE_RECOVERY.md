# Guest database regression recovery

The combined c6fb8a8 CI run 34792603487 exposed three outdated database proofs after the guest acquisition integration. This change repairs their fixtures and assertions without changing application authorization.

- The model registry inventory now includes the three tables created by migration 0037: processing principals, processing leases, and guest submissions.
- The ownership proof scopes lease and acquisition-usage queries to its own tenant. Its module-scoped database also contains the earlier first-guest budget proof; those records must not be confused with this test's two independent submissions.
- The Gemini HTTP report proof now configures an explicit acquisition provider policy for the non-login processing identity, with complete provider/privacy/retention references and supported C4/C5 output bounds. It no longer depends on a learner allowance or a source-bound legacy stage approval to authorize guest processing. The runtime policy check remains enforced.

Validation: all 22 tests across the model-registry, guest-ownership, and guest-submission HTTP modules passed against a fresh disposable loopback PostgreSQL database in 41.59 seconds. The tests exercised source-bound report generation with synthetic provider responses, usage settlement, authorization failures, first-budget initialization, and ownership fencing. No external provider calls or hosted database changes occurred. Ruff format/check passed.

Redacted execution log: `D:/AC-authority-closers-release-audit/sales-ci-database-regressions-20260914.log`; SHA-256 `381a5c42b68c5b62f3c81c90b4b3f0c81cd3d16fcbef91ab754d985d29e0edd0`.
