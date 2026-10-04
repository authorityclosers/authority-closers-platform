# AUT-969: development billing QA fixture

Rework source: latest main `241419fd508ba7582f9ca4f11953b51b42596423`,
started through `ac-gate start billing 969-dev-billing-operator` after AUT-828
merged. Preserved fixture commit `ca5b051` was cherry-picked; this rework
addresses the CTO's PR #285 review, including its session-token blocker.
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
one-use verification challenges without mail. Following AUT-828, the command
takes `CapabilityApplication._governance()` first and refuses unless an
unrevoked platform-scoped `platform_access_manage` grant already exists.
`_insert_grant` writes only the fixed `platform_billing_manage` permission with
`actor_type="operator_data_change"`. Audit actor and session are NULL, with
approver, issue, environment and the fixed grant command ID in the payload.
The non-null grant model's attribution FK names the fictional staff subject,
as in AUT-828; it does not identify an authenticated operator. This command
never bootstraps a manager or makes the fixture staff an owner. The customer setup
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
existing unrevoked manager grant as apply, and cannot bypass an unsafe-state check.
It requires no manager session, token or sign-in.

Apply requires `--apply`, the exact owner identifier, three nonzero recorded
approval-reference UUIDs (data, secrets, billing/settings), and a run UUID.
Root must verify those records cover this exact fixture and development
environment. Arguments record permission; supplying UUIDs does not grant it.
The permanent seed audit uses `operator_data_change` with NULL actor/session
and records the issue, owner, environment, fixed seed command ID, all references,
run, fictional identity IDs and payment ID. The capability grant also carries
its canonical audit with the operator attribution described above. A preview
without authority records no approver, and all prospective audits roll back.

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
| `AC_SESSION_TOKEN_PEPPER` | Existing dev fictional customer setup session and normal sign-in |
| `AC_EMAIL_CHALLENGE_SECRET` | Existing dev registration challenge protection |
| `AC_DEV_BILLING_FIXTURE_PASSWORD_STAFF` | Fictional staff password |
| `AC_DEV_BILLING_FIXTURE_PASSWORD_CUSTOMER` | Fictional customer password |
| `AC_BILLING_FAKE_PROVIDER_SIGNING_KEY` | Dev-only fake signature verification; same value for the released API runtime |

Required configuration: `AC_ENVIRONMENT=development`, existing distinct
`AC_PUBLIC_LEARNER_TENANT_ID` / `AC_OPERATIONS_TENANT_ID`, and the reviewed
`AC_LEARNER_CONSENT_VERSION`. Missing keys are a stop, not an invitation to use
Razorpay credentials or production values. Root does not obtain or inject an
owner/manager session token. The existing access-manager grant is checked under
the governance fence, without impersonating that manager.

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

## Private application dependencies

This development-only tool intentionally uses
`CapabilityApplication._governance`, `CapabilityApplication._insert_grant`,
`Settlement._verified_payment` and `Settlement._sources`. Changes to these
private methods must update this command and its integration proof together.
The `_insert_grant` operator-attribution support is AUT-828's merged output;
this task changes no authorization or billing service module.

## Reproduced checks

All commands exited 0 after the final changes:

```text
ac-gate check
  ok: task/billing/969-dev-billing-operator may be worked on
uv run ruff format --check packages/python tests
  991 files already formatted
uv run ruff check packages/python tests
  All checks passed!
uv run mypy packages/python
  Success: no issues found in 415 source files
uv run pytest tests/unit/test_dev_billing_qa_fixture.py tests/integration/test_dev_billing_qa_fixture_postgresql.py -q -s --tb=short
  30 passed in 33.29s; no skips
```

The migrated PostgreSQL proof used a random test schema on the injected
loopback **test** database. The exact dev-target guard still runs; only the
engine factory is redirected to that disposable schema inside the test.
Provider HTTP is made a test failure during fixture execution. No dev,
staging or production database was connected to or changed by this run.

The proof checks missing and revoked access-manager refusal, NULL grant/seed
audit actor and session, recorded operator attribution, no manager session,
and a minted-then-revoked fictional customer session. It also checks unchanged
table counts/catalogue after preview, collisions,
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
    "staff_person_id": "fef39cd9-641a-4048-b4eb-824eb768ec85",
    "owner_person_id": "e6b237dc-fcde-4313-90ed-d39c092b493a",
    "order_id": "74af54cd-d55a-440e-8ce0-403581638ec6",
    "payment_id": "fake_pay_ac209e6c85dc69e1be",
    "provider": "fake",
    "mode": "test",
    "kind": "subscription.charged",
    "verified_at": "2026-10-04T12:37:55.746954+00:00",
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
