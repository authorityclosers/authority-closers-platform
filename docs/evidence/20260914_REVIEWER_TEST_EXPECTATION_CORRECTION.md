# Reviewer test expectations — 14 September 2026

Application CI `34802883522` completed with 5,427 passing tests and two failures
after both PostgreSQL migration gates passed. No image was packaged. Both failures
were older test expectations that had not followed the independent reviewer
session introduced by migration `20260914_0038`.

## Correction

- The isolated `0001` migration comparison excludes exactly the later Session
  `audience` column and its two constraints, as it already does for later Person
  fields. It still executes the real `0001` migration and compares all original
  columns, nullability and checks. Current schema coverage remains in the model
  registry and actual PostgreSQL migration suites.
- The SQLite fixture explicitly loads the canonical model registry. Running these
  two files alone had exposed a partial-import foreign-key error; collection of
  unrelated tests is no longer required to construct this fixture.
- The Unicode invitation test exercises actual reviewer admission using a current
  reviewer Session and verified active Person fixture with a fixed clock. It
  requires generic NotFound and exactly the two identity queries, proving the
  malformed token never reaches an invitation lookup. The former learner admission
  path must remain unused.

Only two test files changed. Production code, identity checks and migration DDL
are unchanged. Independent Luna xhigh review found no blocking issue or weakened
historical/security assertion.

## Verification

The complete two-file run passed **24 tests in 4.18 seconds**. Ruff check and format
passed. The receipt is retained outside Git at
`D:/AC-authority-closers-release-audit/activation-20260914/reviewer-two-test-correction-v2.xml`.

A broader Windows run was also attempted and retained: 675 passed before its
five-failure limit. Those failures concern POSIX-only credential/file boundaries,
temporary storage rooted inside this repository, and unavailable subprocess
support in the selected Windows event loop. No production guard was relaxed to
make those local checks pass. This partial run is not a full-suite success; the
next exact-source Linux CI run remains required before packaging and deployment.
Its receipts are `reviewer-correction-broad-local.xml` and
`reviewer-correction-broad-local.log` in the same external directory. Earlier
failed receipts are retained.
