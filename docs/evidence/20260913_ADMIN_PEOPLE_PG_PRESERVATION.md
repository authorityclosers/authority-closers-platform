# Admin People shared PostgreSQL fixture preservation

The People lookup/diagnosis PostgreSQL regression previously asserted that five
protected learning tables were globally empty after its scenario. The module uses
one shared PostgreSQL schema, and an earlier canonical admin review test correctly
leaves progress and evidence records there. Full-suite CI therefore failed with one
existing ActivityProgress row even though the People read operation preserved it.

The test now captures every persisted column of every existing row across
ActivityProgress, LearningProgressProjection, ActivityDraft, LearningEvidence, and
EvidenceSubmission before the scenario and compares the complete state afterward.
Rows are sorted for deterministic comparison. The snapshots use separate sessions.
The existing lookup, canonical diagnosis, redaction, tenant/person scope, and audit
assertions remain intact. No production behavior, data model, or migration changes.

## Validation

- Base: `088058adf6b504f2461d5d5fc8e54532e1125e22`.
- Full original PostgreSQL module: **4 passed, 1 failed** in 13.51 seconds, reproducing
  the exact CI global-count failure.
- Full corrected PostgreSQL module: **5 passed** in 15.97 seconds.
- Each run used its own newly created disposable database at the approved local
  PostgreSQL endpoint, with a unique module schema created and removed by the test.
- The API sandbox and other active application databases were not accessed.
- Scoped Ruff lint, Ruff formatting, Python compile, and diff checks passed.
- Independent Luna extra-high review: no blockers; comparison detects inserted,
  removed, or changed protected rows, including existing fixture history.

Evidence packet: `D:/Projects/authority-closers-release-transfer/2026-09-11-recovery/`.
The red/green logs are `ui-admin-people-baseline-postgres.log` and
`ui-admin-people-corrected-postgres.log`. The local runner is
`verify-ui-admin-people-isolation.py`; it reads the approved bootstrap credential
in memory and redacts it from captured test output. No credentials are committed.

This correction resolves the Admin People CI test failure only. The combined
release remains subject to the release owner's other CI and deployment gates.
