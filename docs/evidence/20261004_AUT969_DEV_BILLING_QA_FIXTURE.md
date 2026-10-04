# AUT-969: development billing QA fixture

Implementation source: latest main `8ae81a4b8b00bf8be90ad4ce1c08bb477c58ad27`,
started through `ac-gate start billing 969-dev-billing-fixture`.
`ac-gate check` passed. This is an implementation and isolated PostgreSQL proof,
not a receipt for application to the development database or a deployed journey.

## Fixed fixture and application path

The command is `python -m ac_platform.development.billing_qa_fixture`.
Its identities are fixed, with no email, role, price or provider override:

| Fixture | Identity | Effect |
| --- | --- | --- |
| Staff | `qa-billing-staff-aut969@example.test` | Verified password identity and one platform-scoped `platform_billing_manage` grant |
| Customer | `qa-billing-customer-aut969@example.test` | Verified password identity, public learner membership, one fictional monthly payment |

Seed name: `aut969-billing-qa-v1`. The copied plan name is
`AUT-969 fictional QA`: one seat, 30 minutes, 100 paise per month, test/fake only.
These are fictional fixture values in a process-local `StaticCatalogue`; no
stored catalogue price/status changes. The existing Personal plan row supplies
its stored GST treatment, through the normal checkout service.

`PasswordIdentityService` registers the new identities and consumes their
one-use verification challenges without mail. `CapabilityApplication.grant`
requires an existing authenticated platform access manager; this command never
bootstraps a manager or makes the fixture staff an owner. The customer setup
session is created through the identity service, used for checkout, and revoked
before commit. Its token is not returned.

The checkout service uses isolated fake routing and plan creation, without
adding any `billing_provider_settings` rows. `FakeCheckout.submit` creates a
signed `subscription.charged` callback; `Settlement.receive_webhook` verifies
it, writes the captured subscription payment/period and exactly one 1,800-second
paid lot. This is the application's captured monthly payment representation,
not a fabricated top-up requiring an unrelated period grant. Only verification
grants the seconds. Invoice/order/subscription/ledger history follows existing
services. There is no external checkout, provider HTTP request, real charge,
real refund or renewal job created by this command.

## Preview, apply and refusal rules

Default preview runs the prospective application path in one transaction and
rolls the entire transaction back, including identities, sessions, grants,
audit events and payments. Its JSON shows `applied: false`, `before`, `after`
and `replayed`. Proposed IDs in a new preview are not reserved; apply generates
its own IDs. The preview requires the same credential/configuration inputs and
existing manager authority as apply, and cannot bypass an unsafe-state check.

Apply requires `--apply`, the exact owner identifier, three nonzero recorded
approval-reference UUIDs (data, secrets, billing/settings), and a run UUID.
Root must verify those records cover this exact fixture and development
environment. Arguments record permission; supplying UUIDs does not grant it.
The permanent seed audit records the issue, owner, all references, run, actual
operator person/session, fictional identity IDs and payment ID. The capability
grant also carries its normal canonical audit.

Both modes refuse any target other than environment `development`, driver
`postgresql+psycopg`, host `acdev-postgres`, port 5432, database `ac_platform`,
and user `ac_runtime`. URL query routing, ambient `PG*` variables, live mode,
and configured Razorpay credentials are refused before connecting. Any
non-fake or non-test provider settings history is refused, including disabled
history. Missing fixture credentials refuse before connecting; messages name
missing variables only. Other driver/identity failures are sanitized.

A fixed email already present without the seed audit refuses the entire
transaction. No existing identity or password is repaired. A repeated apply
reads and authenticates the original fixture, checks its original grant and
payment ownership, and returns the original verification timestamp and audit.
It adds no rows, and never renews the refund window or replaces the payment.
Revoked grants, changed identity/membership/payment facts, closings, use of paid
minutes, refunds, or a closed seven-day window refuse a refresh. Refund
eligibility uses the normal Personal ledger projection, including derived trial
capacity and all recorded usage, followed by `payment_refundable`.

The existing AUT-417 learner is unchanged. AUT-514's three learner fixtures and
their module are unchanged. Only the new module, its focused tests and this
document are added. The command and all its guards are kept together as one
reviewable executable; no unchecked partial apply command is introduced.

## Inputs for Root (names only)

Use separate Infisical **`dev`**, path **`/application`**. No values were read,
created, copied or disclosed in this implementation run.

| Name | Purpose |
| --- | --- |
| `AC_DATABASE_URL` | Runtime-role URL for the exact dev endpoint above |
| `AC_SESSION_TOKEN_PEPPER` | Existing dev identity session validation |
| `AC_EMAIL_CHALLENGE_SECRET` | Existing dev registration challenge protection |
| `AC_DEV_BILLING_FIXTURE_PASSWORD_STAFF` | Fictional staff password |
| `AC_DEV_BILLING_FIXTURE_PASSWORD_CUSTOMER` | Fictional customer password |
| `AC_DEV_BILLING_FIXTURE_OPERATOR_SESSION_TOKEN` | Current dev session of an existing platform access manager; short-lived operator injection only |
| `AC_BILLING_FAKE_PROVIDER_SIGNING_KEY` | Dev-only fake signature verification; same value for the released API runtime |

Required configuration: `AC_ENVIRONMENT=development`, existing distinct
`AC_PUBLIC_LEARNER_TENANT_ID` / `AC_OPERATIONS_TENANT_ID`, and the reviewed
`AC_LEARNER_CONSENT_VERSION`. Missing keys are a stop, not an invitation to use
Razorpay credentials or production values. Root owns obtaining the existing
manager session through ordinary sign-in and handling it without logging it.

From the reviewed released tree, inside the approved dev network with those
inputs injected, preview:

```sh
python -m ac_platform.development.billing_qa_fixture
```

Only after Root verifies explicit data, secrets and billing/settings authority,
apply the same released command, replacing the placeholder references with the
actual recorded UUIDs (never credential values):

```sh
python -m ac_platform.development.billing_qa_fixture --apply \
  --approver ZyTZxLQfn8zFPFVZ5OjwisIX96Xmo4j0 \
  --data-approval <recorded-data-approval-uuid> \
  --secrets-approval <recorded-secrets-approval-uuid> \
  --billing-approval <recorded-billing-settings-approval-uuid> \
  --run-id <operator-run-uuid>
```

Normal staff sign-in surface: `https://admin-dev.authorityclosers.com/login`,
using the fictional staff credentials through the existing password sign-in.
The command does not log a browser in or bypass Cloudflare Access. The tested
canonical endpoint is `POST /v1/auth/password/login` on the Admin origin.
Root separately verifies the released dev Admin/API configuration. To expose
billing commands, the API needs the explicitly authorized
`AC_BILLING_ENABLED=true` and fake signing key; this script does not change
either setting or enable a catalogue for public sale. Root checks the app's
Admin billing readback and posts the actual apply receipt on AUT-959.

## Reproduced checks

All commands exited 0 after the final changes:

```text
ac-gate check
  ok: task/billing/969-dev-billing-fixture may be worked on
uv run ruff format --check packages/python tests
  954 files already formatted
uv run ruff check packages/python tests
  All checks passed!
uv run mypy packages/python
  Success: no issues found in 397 source files
uv run pytest tests/unit/test_dev_billing_qa_fixture.py tests/integration/test_dev_billing_qa_fixture_postgresql.py -q -s --tb=short
  31 passed in 28.02s; no skips
```

The migrated PostgreSQL proof used a random test schema on the injected
loopback **test** database. The exact dev-target guard still runs; only the
engine factory is redirected to that disposable schema inside the test.
Provider HTTP is made a test failure during fixture execution. No dev,
staging or production database was connected to or changed by this run.

The proof checks unchanged table counts/catalogue after preview, collisions,
remote/live history refusal, duplicate apply, wrong credentials, revoked grant,
closed window, changed lot, and paid use. It verifies that usage before the
payment can consume trial capacity without invalidating this payment. It signs
the staff in through HTTP, reads the canonical billing overview and exercises
`POST /v1/platform/billing/payments/{payment_id}/refund`: the accepted command
returns **202 / pending**, followed by stored **refunded** state from the
fake-provider receipt and append-only holds/releases/refund history. A replay
after that refund refuses to mint a replacement. The audit hash chain verifies.

Sample content-free **isolated test** readback, captured before the test's QA
refund (the test schema has subsequently been removed). Approval-reference
UUIDs in the full test output are fictional test inputs, not actual permission:

```json
{
  "applied": true,
  "before": {"seed_present": false},
  "after": {
    "seed": "aut969-billing-qa-v1",
    "issue": "AUT-969",
    "audit_id": "3ee5ea49-5e7f-5d27-a978-a16ef5fdd456",
    "staff_person_id": "94ca78d1-0090-418d-beb9-5cb5ce53c083",
    "owner_person_id": "c5269d0e-2d76-41d9-9270-129276688740",
    "order_id": "59ae0161-7e21-474a-90c3-46941b43f9c5",
    "payment_id": "fake_pay_ac7b574f90fa2cc97c",
    "provider": "fake",
    "mode": "test",
    "kind": "subscription.charged",
    "verified_at": "2026-10-04T04:31:15.924899+00:00",
    "unused_minutes": 30
  },
  "replayed": false
}
```

The actual `after` object also includes `authority` with `approver`,
`data_approval`, `secrets_approval`, `billing_approval` and `run_id`; UUIDs are
JSON strings. Repeat-run `before` and `after` are identical, `replayed` is true,
and the original authority remains intact. CI, CTO review, CEO approval, merge
and Root's authorized dev application/readback remain release requirements.
