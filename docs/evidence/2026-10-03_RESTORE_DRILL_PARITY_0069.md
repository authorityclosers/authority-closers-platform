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

Verification on the billing checkout:

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

PR B boundary: the implementation is about 530 production lines including the
migration and three parity tools. It can be reviewed as a schema/settings/parity
commit (about 253) followed by a settlement/buyer/GST-flag commit (about 280).
The card requires three PRs and about 300 lines per PR; CTO must reconcile this
boundary before a PR is opened. Listing/download remains the separate PR C.
