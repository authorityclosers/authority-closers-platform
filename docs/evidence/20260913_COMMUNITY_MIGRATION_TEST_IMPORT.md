# Community identity migration test import repair

Date: 2026-09-13 (Asia/Kolkata). Scope: test loading only.

## Failure and implementation

Release CI run `34713937665` reported 4,074 passing Python tests and four
failures. Two failures were the community identity migration collision-preflight
and legacy-backfill tests: importing `db.migrations.versions.20260910_0028_global_community_identity`
raised `ModuleNotFoundError: No module named 'db'`. Pytest uses
`--import-mode=importlib`; the migration directory is not an installed application
package, so tests must not depend on the checkout root being importable.

Both affected tests now use a shared file-location loader. It resolves the exact
migration from the test file's location, checks the import specification and
loader, and executes the migration module definitions. This follows the existing
file-location loading approach in `tests/database/test_catalog.py`. It does not
modify `sys.path`, environment variables, migration code, database fixtures, or
the test assertions. The collision checks, unchanged-count check, backfill
provenance, preference preservation, and legacy-history checks remain intact.

## Verification

- Ruff format and Ruff check passed for the changed integration test file.
- Python 3.12 isolated-mode proof (`python -I`) ran from the external recovery
  packet directory with the repository absent from `sys.path`. The original
  package import reproduced `ModuleNotFoundError: No module named 'db'`.
- The proof extracted and executed the actual new loader using the test file's
  `__file__`. It loaded the exact migration, checked revision `20260910_0028`,
  predecessor `20260910_0027`, and the preflight/upgrade/downgrade callables.
- AST comparison against the prior committed tests confirmed that both complete
  test bodies after their migration-loading assignment are unchanged. Migration
  source bytes, normalized for checkout line endings, also match the prior commit.
- Independent read-only review found no P0/P1/P2 defects in the final patch.

The isolated proof executed no database operations or migration functions. The
two PostgreSQL integration cases still require the central Linux CI rerun; this
document does not claim that rerun passed. Other failures in the same CI run are
handled by the release owner and scanner lane.

## Retained receipts

Recovery packet: `D:\Projects\authority-closers-release-transfer\2026-09-11-recovery`.

- `probe-community-migration-import-20260913.py`, SHA-256
  `7da11579b65c21554774703d384c619aa1b0f735849f3ec46e731cfd66f35a82`.
- `community-migration-import-proof-20260913.json`, SHA-256
  `4c1602107358e47acc7b578907232d777cb891555740a72501139174dd4def37`.
- Verified test source SHA-256:
  `a96df372fb3d6a142a60b5d8443541fe500613e8a36041191fb02be01cf849d8`.
- Unchanged migration source SHA-256:
  `648adc46d79defeb77aa3c61d9e5f434cc601de264f888ffc733f68966fbb4b7`.

The failed CI receipt is retained as `pr56-ci-failure-34713937665.log` in the same
packet. This repair supersedes the test import failure without replacing that
failure evidence or weakening either integration test.
