# AUT-901: tenant trial composition

Source: latest main `88e361eb9f93fce6b32a470884b1b371e29def3c`.
Contract: AUT-560 plan revision `d3daabe0-54f7-4052-bd30-83bb129ef7b7`,
ADR 0052: only the public learner tenant has a derived trial.

The merged organisation-pool implementation already projects pools without a
trial (`BillingLedger.project_organisation`). Checkout and Admin minute-grant
construction still omitted `trial_enabled`, so the recorded construction
finding remained. This change reuses one tenant comparison in `billing/trial.py`
for checkout, acquisition runtime and `http/operations.py` minute grants.
Checkout uses the resolved Personal or selected Organisation tenant. Its
`ledger()` requires an explicit tenant keyword. Settlement passes the billing
account's tenant in every call, including Personal refund eligibility; the
development billing QA fixture passes its Personal account's tenant too.

Regression evidence:

- Checkout account resolution enables Personal trials under v1/v2 and disables
  Organisation trials, including a member's grant account projection. A
  600-second grant remains 600 seconds; Personal adds the existing trial.
- The actual acquisition runtime passes the same flag to its ledger.
- Real Admin minute-grant HTTP calls in separate disposable PostgreSQL schemas
  construct Personal with trials enabled and Organisation with trials disabled.
  A ten-minute grant returns shared availability 4200/600 seconds respectively.
- Existing pool concurrency, Personal golden parity, projection properties,
  checkout settlement/refund and audited/idempotent grant tests pass.

Initial-head checks at `01bf385` (exit 0):

```text
ac-gate check
uv run ruff format --check packages/python tests
uv run ruff check packages/python tests
uv run mypy packages/python
uv run pytest tests/unit/billing/test_trial.py tests/unit/billing/test_projection.py tests/unit/billing/test_ledger.py tests/unit/billing/test_tenant_trial_composition.py tests/unit/http/test_conversation_learner_acquisition.py -q
uv run pytest tests/database/test_billing_ledger_postgresql.py tests/database/test_billing_org_pool_postgresql.py tests/database/test_billing_checkout_postgresql.py tests/integration/test_operations_http_postgresql.py::test_account_minute_grants_are_finite_audited_idempotent_and_tenant_scoped_postgresql -q --junitxml "$PAPERCLIP_RUN_SCRATCH_DIR/AUT901-pg.xml" -o junit_family=xunit1
git diff --check
```

Initial results: 1008 Python files formatted; lint clean; mypy clean for 419 source
files; 103 unit tests passed; 37 PostgreSQL tests passed. Early test-fixture
failures were corrected (fresh capability-bootstrap schemas, FastAPI Request
annotation, SQLite async get adapter); the final suites above are green.

To check on dev: with the existing disposable loopback test database injected,
run the two pytest commands above from the billing checkout. After merge and
normal deployment, record dev/staging release SHAs and compare read-only
Personal and Organisation session/usage responses using approved fictional
fixtures. An empty Organisation must have no trial; grant capacity must agree
with its pool. Runtime rollout evidence is still required before closing the
task. This receipt proves the local dev fixtures, not deployment.

HTTP request/response models are unchanged. No API fields are added. CI,
SHA-bound CTO review, CEO merge approval and deployed dev/staging verification
follow this implementation handoff.

## CTO requested revision

The CTO review identified a Personal refund regression at `01bf385`: settlement
called `ledger()` without a tenant, which silently omitted the v2 trial. The
earlier receipt's claim that these calls were only entry readers/writers was
incorrect. Refund eligibility projects actual usage and must include the trial.

The new PostgreSQL regression was first run against that head:

```text
uv run pytest tests/database/test_billing_settlement_postgresql.py::test_personal_v2_trial_usage_leaves_paid_lots_refundable -q --tb=short
```

Result: **1 failed**, `PaymentUsed` in `Settlement._prepare_refund`, reproducing
the finding before the production correction.

Correction: require the tenant keyword and pass the account tenant at all four
settlement construction sites and the development QA readback. The unit
composition regression now rejects omitted tenant arguments; every remaining
production caller supplies one. Changes in `billing/settlement.py` and
`development/billing_qa_fixture.py` were explicitly approved by the CTO review.

Regression proof uses fictional accounts and signed fake-provider events in
disposable loopback PostgreSQL schemas. A Personal v2 account buys a period and
top-up, reserves and settles 600 seconds, and allocates all of that usage to its
14-day trial. Both fresh paid lots remain unallocated and are refunded through
the real billing application and settlement path, with hold/release/refund
history. The matching Organisation scenarios run v2 with trials disabled:
pending and settled member usage allocate 600 seconds to the pool's top-up lot,
and refuse the refund before any provider call. Unused/legacy-grant cases retain
their existing refund and pool behaviour.

Revision validation (exit 0):

```text
ac-gate check
ac-gate pr-check 333
uv run ruff format --check packages/python tests
uv run ruff check packages/python tests
uv run mypy packages/python
uv run pytest tests/unit/billing/test_trial.py tests/unit/billing/test_projection.py tests/unit/billing/test_ledger.py tests/unit/billing/test_tenant_trial_composition.py tests/unit/http/test_conversation_learner_acquisition.py tests/unit/test_dev_billing_qa_fixture.py -q
uv run pytest tests/database/test_billing_settlement_postgresql.py tests/database/test_billing_org_refunds_postgresql.py tests/database/test_billing_refund_safety_postgresql.py tests/integration/test_dev_billing_qa_fixture_postgresql.py -q --junitxml "$PAPERCLIP_RUN_SCRATCH_DIR/AUT901-review-pg.xml" -o junit_family=xunit1 --tb=short
git diff --check
```

Results: 1008 Python files formatted; lint clean; mypy clean for 419 source
files; **132 unit tests and 41 PostgreSQL tests passed**. Gate continuation and
PR file-overlap checks pass. Run the revision pytest commands above on dev with
the existing disposable loopback database environment to reproduce the refund
and fixture checks. No provider network, live charge, account/settings/price
change, schema migration or production data operation occurred. Deployed
dev/staging verification remains pending the normal reviewed release path.
