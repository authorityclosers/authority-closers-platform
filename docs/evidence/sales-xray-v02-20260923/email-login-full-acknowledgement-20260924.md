# Email login full acknowledgement evidence

Date: 2026-09-24

## Contract

The email login challenge carries the explicit 18+ attestation with the exact
current learner consent version. `email_login_codes.age_attested` is non-null
and defaults to false, so challenges written before migration `20260924_0048`
cannot create a learner or complete first mailbox verification. New account
creation and first mailbox proof require both the current consent version and
`age_attested=true` at challenge issuance and consumption. Existing verified,
non-privileged email sign-in remains available without consent mutation or a
new consent event; privileged identity checks are unchanged.

On successful new-account creation or first mailbox proof, the service returns
the prior consent version/timestamp and an audit gate. The email verification
route records `identity.learner_consent_accepted.v1` with the accepted version,
18+ declaration, prior consent snapshot, and `accepted_via=email_otp` inside the
same transaction that provisions the learner and issues the session. The
immutable audit event preserves the acceptance if the current challenge row is
later reused for another generation.

## Changed surfaces

- `packages/python/ac_platform/identity/models.py`
- `packages/python/ac_platform/identity/email_login.py`
- `db/migrations/versions/20260924_0048_email_login_age_attestation.py`
- `packages/python/ac_platform/http/auth.py` (request contract and same-unit
  audit wiring, owned by the authentication implementation lane)
- `tests/integration/test_password_identity_http_postgresql.py`
- `tests/integration/test_sales_xray_account_http_postgresql.py`
- `tests/e2e/test_sales_xray_acquisition_browser.py`

## Verification

- Ruff passed for the changed service, model, migration, and email/account test
  files.
- `tests/unit/http/test_auth_routes.py` and `tests/unit/worker/test_worker.py`:
  119 passed.
- The PostgreSQL email/account integration modules collected 21 tests, all
  skipped because neither `AC_PASSWORD_HTTP_POSTGRES_TEST_URL` nor
  `AC_TEST_DATABASE_URL` is configured. Their fixture refuses non-local
  PostgreSQL unless explicitly overridden; no database URL was present here.
- Alembic reports `20260924_0048` as the single migration head.
- `git diff --check` passed.

The actual PostgreSQL migration and transaction assertions remain for CI or a
configured loopback PostgreSQL test database; no database integration pass is
claimed here.
