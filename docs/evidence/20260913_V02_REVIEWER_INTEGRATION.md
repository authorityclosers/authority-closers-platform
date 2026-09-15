# v0.2 reviewer integration

The reviewer persistence change `80df3e257e1f08fae3ebaf1a049c6f8b07c0b996`
is integrated as `7a6dce7` on `codex/v0.2-consolidation-20260913`.
Assignments bind a verified reviewer to one existing call and report. Sales,
technical and UX submissions retain the authenticated author and append history;
they do not apply canonical corrections or publish autonomous scores.

Validation on the combined source, 2026-09-13:

- 788 reviewer contract, HTTP, model registry, backup parity and restore tests
  passed in 36.23 seconds. Two restore integration cases were skipped because
  the local Docker daemon and an approved restore dump were unavailable.
- Five actual PostgreSQL reviewer cases passed in 17.37 seconds, including
  persisted report/submission reload, retry idempotency, cross-account denial,
  revocation, expiry, source/permission changes, UX metadata and erasure.
- The populated 0033-to-0034 migration rehearsal passed in 30.21 seconds in a
  newly created disposable local database, preserving existing rows.
- Ruff lint and formatting passed; mypy passed all 254 Python source files.

Receipts are retained outside Git in `D:/AC-authority-closers-release-audit/`:
`v02-review-integration-01.xml`, `v02-review-postgresql-01.xml`, and
`v02-review-migration-01.xml`. The PostgreSQL proof used the current native build
whose manifest and executable both identify SHA-256
`b4ac897627daf8f41f807370ad7cfcda11639faf891c4d47d57b377feea6bca8`, bound to source
`40b8b05256986da5eb5d49c3b3cb48c52d511117ecf2e59d56849457cb12fae3`.
The older binary digest from the earlier ledger was not reused.

Independent backend review and final UI integration are separate acceptance
steps. No staging/production reviewer availability, real-call processing or
browser save/reload is claimed by these local proofs. The Chrome automation
native pipe was unavailable after a retry and fresh session initialization;
browser acceptance remains outstanding.
