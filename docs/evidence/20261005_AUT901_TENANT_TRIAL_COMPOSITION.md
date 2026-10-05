# AUT-901: tenant trial composition

Source: latest main `88e361eb9f93fce6b32a470884b1b371e29def3c`.
Contract: AUT-560 plan revision `d3daabe0-54f7-4052-bd30-83bb129ef7b7`,
ADR 0052: only the public learner tenant has a derived trial.

The merged organisation-pool implementation already projects pools without a
trial (`BillingLedger.project_organisation`). Checkout and Admin minute-grant
construction still omitted `trial_enabled`, so the recorded construction
finding remained. This change reuses one tenant comparison in `billing/trial.py`
for checkout, acquisition runtime and `http/operations.py` minute grants.
Checkout uses the resolved Personal or selected Organisation tenant. Calls
without a tenant are settlement entry readers/writers and derive no trial;
their lot, refund and usage operations are unchanged.

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

Final checks (exit 0):

```text
ac-gate check
uv run ruff format --check packages/python tests
uv run ruff check packages/python tests
uv run mypy packages/python
uv run pytest tests/unit/billing/test_trial.py tests/unit/billing/test_projection.py tests/unit/billing/test_ledger.py tests/unit/billing/test_tenant_trial_composition.py tests/unit/http/test_conversation_learner_acquisition.py -q
uv run pytest tests/database/test_billing_ledger_postgresql.py tests/database/test_billing_org_pool_postgresql.py tests/database/test_billing_checkout_postgresql.py tests/integration/test_operations_http_postgresql.py::test_account_minute_grants_are_finite_audited_idempotent_and_tenant_scoped_postgresql -q --junitxml "$PAPERCLIP_RUN_SCRATCH_DIR/AUT901-pg.xml" -o junit_family=xunit1
git diff --check
```

Results: 1008 Python files formatted; lint clean; mypy clean for 419 source
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
