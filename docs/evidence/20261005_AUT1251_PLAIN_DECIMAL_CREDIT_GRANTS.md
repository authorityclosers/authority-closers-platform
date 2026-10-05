# AUT-1251: plain-decimal staff credit grants

Task: [AUT-1251](/AUT/issues/AUT-1251).
Decision: [CEO plain-decimal rule](/AUT/issues/AUT-993#comment-cd5ef576-21bf-497d-acb5-e979c896e044).
Source: latest main `33fc09247b72884fb46a7bcf9c21584cbb6b1c46`.
Program context: AUT-560 plan revision `d3daabe0-54f7-4052-bd30-83bb129ef7b7`.

Latest main's `CreditGrantRequest.quantity` had no pattern and admitted `1E+2`.
The boundary now applies the exact decided pattern `^[0-9]+(\.[0-9]+)?$` to
its existing strict string field, before the existing positive/finite/exact
quantity validator. Grant service, authority, receipts, retries, ledger and
audit behavior are unchanged.

Regression proof before the production edit:

```text
uv run pytest tests/unit/http/test_staff_credit_grants.py -q -k '1E+2'
```

Result: exit 1, one failing regression; the original route returned 200 instead
of 422. After the edit, integer and fractional strings, small fractions and
leading/trailing decimal zeros pass. Scientific notation, signs, omitted digits,
whitespace, underscores, non-ASCII digits and non-string quantities are refused
before the grant service. Existing zero, finite and exact-quantity checks remain.

Final verification (all exit 0):

```text
ac-gate check
uv run ruff format --check packages/python tests
uv run ruff check packages/python tests
uv run mypy packages/python
uv run pytest tests/unit/http/test_staff_credit_grants.py tests/integration/test_staff_credit_grants_http_postgresql.py tests/database/test_credit_grants_postgresql.py -q
uv run pytest tests/unit/billing/test_credit_grants.py tests/unit/billing/test_credits.py -q
git diff --check
```

Results: 1008 Python files formatted; lint clean; mypy clean for 419 source files;
105 HTTP/domain tests plus 49 billing unit tests passed. The first suite includes
54 HTTP unit cases and 51 disposable PostgreSQL checks, with zero skips.
The new PostgreSQL `1E+2` case verifies unchanged credit-entry, credit-audit and
account counts. Existing self-grant refusal, tenant isolation, fresh authority,
idempotent/concurrent retries, conflicting facts, exact quantities, immutable
history, transaction rollback and minute/provider isolation regressions pass.

API contract: `POST /v1/platform/billing/accounts/{tenant_id}/{account_id}/credit-grants`
retains `Idempotency-Key`, the authenticated Admin session and safe origin.
The body is `{"quantity":"1.25","reason":"Fictional support grant"}`;
`quantity` is a positive exact string matching the pattern and `reason` is a
nonblank string of 1–500 characters. Extra body fields remain forbidden.
The 200 receipt retains six string fields: `entry_id`, `account_id`, `quantity`,
`source_ref`, `audit_event_id`, `created_at`. Invalid notation returns 422 from
request validation; existing application error and receipt formats are unchanged.

To check on dev: run the two pytest commands above in the billing checkout with
the existing explicit disposable loopback PostgreSQL URL injected. The harness
migrates isolated random schemas, uses fictional accounts and cleans its schemas.
No deployed database writes were made. After the approved merge and normal
deployment, record dev and staging release SHAs and read the deployed OpenAPI
quantity pattern where the schema endpoint is available. Reproduce HTTP behavior
only in the disposable fixture. This receipt covers local dev checks; deployed
dev/staging verification remains part of delivery before task closure.
