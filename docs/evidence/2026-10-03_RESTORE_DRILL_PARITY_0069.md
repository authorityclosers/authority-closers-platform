# AUT-878: tax-document migration and restore parity

Migration `20261003_0069` follows merged `20261003_0068`. The new v41 contract
adds `billing_invoice_counters`, `billing_buyer_tax_details`, `billing_invoices`
and `billing_credit_notes` to the existing 0068 table set. Historical contracts
remain unchanged. Backup capture, restore proof and application restore drill
carry the same head, contract and table set. The release admission test pins
0069 so an older installed backup tool refuses that release before migration.

Forward-only migration and append-only triggers are covered on an explicit
loopback disposable PostgreSQL schema, with fictional buyers/payments only.
No dev/staging/production data, seller configuration, provider setting or keys
are changed by this work. This is local implementation evidence; it does not
claim a deployed payment or a full production snapshot/restore exercise.

Initial combined-B verification, before the B1/B2 split and review changes:

- `uv run ruff format --check packages/python tests`: exit 0, 905 files.
- `uv run ruff check packages/python tests`: exit 0.
- `uv run mypy packages/python`: exit 0, 382 source files.
- `uv run pytest tests/database/test_billing_invoices_postgresql.py -q --tb=short`:
  6 passed. Signed Personal and two-seat Organisation payments; CGST/SGST and
  IGST; immutable snapshots and replay; two tenant sessions demonstrably waiting
  on the FY row; consecutive numbers; full refund/one credit note; all four
  UPDATE/DELETE triggers; stored GST flag and historical read preservation.
- `uv run pytest tests/unit/billing/test_invoices.py tests/unit/application/test_settings.py tests/database/test_billing_settlement_postgresql.py tests/database/test_billing_refund_safety_postgresql.py -q --tb=short`:
  211 passed before adding the standalone forward-only migration unit proof;
  one existing test-client deprecation warning.
- `uv run pytest tests/unit/billing/test_invoices.py -q`: 8 passed after adding
  that proof; one existing test-client deprecation warning.
- `uv run pytest tests/database/test_model_registry.py tests/database/test_conversation_postgresql.py::test_populated_migration_head_matches_real_model_registry -q --tb=short`:
  8 passed; migrated schema and real model metadata match.
- `uv run pytest tests/unit/http/test_billing_routes.py tests/database/test_billing_checkout_postgresql.py tests/infra/test_ac_release.py tests/infra/test_capability_backup_parity.py -q`:
  121 passed, 3151 root-only cases skipped, one existing warning. Passwordless
  sudo is unavailable; no root-only metadata/restore pass is claimed.
- The pure `test_three_separately_packaged_helpers_have_identical_versioned_contracts()`
  assertion was also executed directly: all historical heads and 0069/v41
  match across the three independently packaged tools.
- `ac-gate check`: exit 0, this task branch may be worked on.

The first passes found an omitted-buyer idempotency digest regression, the
legacy Organisation flag expectation, an undersized fictional organisation
token, and the immediate processed-refund receipt path. The digest preserves
older requests, the expectation reflects the saved flag, the fixture meets the
existing minimum, and both receipt/webhook refunds now use the shared credit
note path. Final focused reruns above passed. No tests ran against production.

The CTO approved A/B1/B2/C on 3 October. PR #235 contains B1 only; B2 is preserved
as commit `63f9f2a` and a task attachment, with a 615-line allowance after B1
merges. Listing/download remains PR C.

B1 review changes: all four table creations have literal names, invoice numbers
are constrained to 16 allowed characters, the prefix defaults to EA and accepts
only 1–2 uppercase letters/digits, and tax amounts/place of supply are typed
columns with currency, nonnegative, balance and component checks. GSTIN/SAC stay
empty. B2 must adopt the compact four-digit financial year, typed money columns
and text-only snapshots when cherry-picked.

The root-skipped parity test hid missing 0069 count/contract expectations and
an out-of-order new-table entry. Both are fixed alongside the literal-name CI
failure. Direct invocation of the two pure assertions (packaged contracts and
exact migration tables/counts) now passes. The full root-only file is required
before the next push; Root Operator must supply a receipt for the corrected SHA.

Revised B1 local checks: format 902 files, lint and mypy 381 sources passed.
`uv run pytest tests/unit/application/test_settings.py tests/database/test_model_registry.py tests/database/test_conversation_postgresql.py::test_populated_migration_head_matches_real_model_registry tests/infra/test_ac_release.py tests/infra/test_capability_backup_parity.py -q --tb=short`
passed 273 cases with 3151 root-only skips.
These skips do not prove the complete parity gate. No production restore is run.

Root AUT-960 subsequently verified the unchanged `6cea6a8` source with 3151
parity cases passed and no skips. Its receipt is task attachment
`b9bd357f-d1c5-4dc0-b182-1cd2ac114adf`; this proves that earlier SHA only.

The CEO then found SQLite registry setup failures in CI: PostgreSQL's `~`
operator appeared in both document models' number CHECK. The shared constraint
now uses the existing `.ddl_if(dialect="postgresql")` idiom. The frozen 0069
migration is unchanged. Compiling both tables confirms PostgreSQL retains the
regex CHECK and SQLite omits it; the other money/number constraints stay intact.

Verification for the SQLite correction (all exit 0):

- `uv run ruff format --check packages/python tests`: 902 files formatted.
- `uv run ruff check packages/python tests`: passed.
- `uv run mypy packages/python`: 381 sources, no issues.
- `uv run pytest tests/unit/bootstrap/test_operations_only.py tests/unit/application/test_settings.py tests/database/test_model_registry.py -q --tb=short`:
  219 passed, including SQLite creation of the complete model registry.
- A direct `uv run python -` SQLAlchemy `CreateTable` compilation for both
  document tables under PostgreSQL and SQLite verified the CHECK's dialect.

Per the CTO and CEO's revised verification instruction, the new head's full
parity receipt comes from CI; no further Root verification task is created.
The new head requires CTO review followed by CEO approval before merge.
