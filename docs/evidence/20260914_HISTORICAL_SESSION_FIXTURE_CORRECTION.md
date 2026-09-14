# Historical session fixture correction — 14 September 2026

The reviewer identity migration adds `sessions.audience` at0038. The current Session ORM therefore cannot seed schemas deliberately pinned to older migration heads. CI34801138643 failed on the populated0022 Studio proof before the application suite ran.

Base: `ebe1b0bb6c57d6bba432e96b81882fb283573228`.
Scope: four test files and these receipts. Application code, identity rules, migrations and deployment configuration are unchanged.

## Change

- Studio's populated0022 proof reflects its actual historical sessions table for fixture insertion. It asserts0022 and0023 explicitly and confirms that neither has `audience`. The real catalog commands, operation rejection before0023, replay, audit verification and immutable-receipt checks remain. Current-head Studio tests continue using the current ORM.
- Populated0032 Sales fixtures insert into the reflected historical sessions table, matching their existing reflected plan/authorization fixtures. Full-row preservation across0033,0034 and0035 remains checked.
- Capability tests retain a separate0018→0019 schema for historical DDL, metadata, cross-tenant relationships and immutable history. Tests using the current Identity/Capability applications receive an independent schema migrated to head; they retain real lock, authorization, revocation, replay and atomic-audit checks.

No test is skipped, no future column is added to an old schema, and no production compatibility behavior is changed.

## Actual receipts

| Execution                                    | Result                                                               | Receipt                                                                                         |
| -------------------------------------------- | -------------------------------------------------------------------- | ----------------------------------------------------------------------------------------------- |
| Original Studio and populated0032/0033 cases | 3 failed; all missing `sessions.audience`                            | [before.junit.xml](historical-session-fixtures-20260914/before.junit.xml)                       |
| Original capability suite                    | 4 failed, 6 passed; the four service cases lack `sessions.audience`  | [capability-before.junit.xml](historical-session-fixtures-20260914/capability-before.junit.xml) |
| Corrected full four-file suite               | 27 passed, zero failures/errors/skips; pytest reported162.80 seconds | [after.junit.xml](historical-session-fixtures-20260914/after.junit.xml)                         |

The corrected execution includes both Studio files, the entire migration rehearsal file and the entire capability PostgreSQL file. Ruff check/format and `git diff --check` passed. The independent Luna review is recorded in the companion review receipt.

All executions used an explicitly configured loopback PostgreSQL database with a new generated name and isolated schemas. The runner confirmed disposal of each database. Synthetic fixture values only; approved local connection credentials remained inside the runner process and were scrubbed from retained output. No provider call, paid inference, hosted mutation or deployment occurred in this proof.

## Sweep

Searched explicit historical migration invocations and Session imports across tests. The other activity-media0015, practice0019→0021 and conversation0029 harnesses migrate to head before Session fixture use. The catalog0009 migration proof does not seed Session. No other test module imports the capability harness. Existing shared Studio seed consumers keep the default current-ORM path.

Source hashes, parsed JUnit counts and runner attribution are in [summary.json](historical-session-fixtures-20260914/summary.json). The hash index binds the committed test source and normalized evidence files. External originals are retained at `D:/AC-authority-closers-release-audit/historical-session-fixtures-20260914/`.

These receipts establish the fixture correction locally. Final combined CI, immutable image packaging and staged/production verification remain the release owner's next steps.
