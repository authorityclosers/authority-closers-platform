# Operations HTTP PostgreSQL test schema isolation

The operations HTTP integration module used one module-scoped PostgreSQL schema for four tests. Each test seeded unique people and tenants, but the capability table is global to the schema. The minute-grant integration test correctly created and retained a first-manager capability grant. The following minute-account-target-resolution test then called `CapabilityApplication.bootstrap_first_manager()` for another seeded owner and correctly received `CapabilityConflict("Permission history exists; use a named platform manager.")`.

The failure reproduced on the synthetic loopback PostgreSQL 18.6 database, with the two affected tests selected in their module order: `test_account_minute_grants_are_finite_audited_idempotent_and_tenant_scoped_postgresql` passed, then `test_minute_account_target_resolution_is_exact_audited_and_public_tenant_scoped_postgresql` failed at its bootstrap setup. This is test fixture leakage, not an application authorization defect.

`postgres_harness` now creates and drops a fresh migrated schema per test. It does not delete capability grants or audit records to reset state. The target-resolution test additionally proves that a second bootstrap in its own schema is still refused after the first grant, then continues to exercise the authorized lookup path and its denied/unverified/cross-tenant cases.

Verification against the disposable local-only database:

- The red reproduction used the two affected tests in module order and produced `1 passed, 1 failed` at the intended prior-history guard. After the fixture change, the same selection passed `2 passed`.
- The complete affected module passed `4 passed`.
- A final single-test rerun after import-only cleanup passed the test body but encountered a disposable-cluster teardown error while dropping its schema: PostgreSQL reported `could not open file "base/16384/1249_fsm": Invalid argument`. No test assertion failed in that rerun; the full-module run above had completed cleanly. The private cluster was stopped afterward.
- Ruff check and format check passed for the changed test module.

Commands were run from the repository root using the shared Python 3.12 test environment. The test URL is trust-authenticated loopback-only and contains no password:

```powershell
$env:AC_OPERATIONS_HTTP_POSTGRES_TEST_URL='postgresql+psycopg://ac_owner@127.0.0.1:35438/minute_target_ci'
python -m pytest -q tests/integration/test_operations_http_postgresql.py::test_account_minute_grants_are_finite_audited_idempotent_and_tenant_scoped_postgresql tests/integration/test_operations_http_postgresql.py::test_minute_account_target_resolution_is_exact_audited_and_public_tenant_scoped_postgresql --tb=short
python -m pytest -q tests/integration/test_operations_http_postgresql.py --tb=short
```

The disposable PostgreSQL cluster was confined to `C:\Users\Suyash\.codex\private-artifacts\minute-target-ci-postgres-20260925` on loopback port `35438`. It was created with local trust for synthetic test data only; no staging or production database was accessed.
