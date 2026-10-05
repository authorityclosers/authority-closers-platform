# AUT-1156: billing QA credential contract

Source: latest main `e63899342d8d122e83bb01690c280640c9c1bbe3`, claimed with
`ac-gate start devenv 1156-billing-qa-contract`. The deleted AUT-1191 task branch
was finished with the gate's `done` before starting. `ac-gate check` passed.

Both transport tables now match the unchanged AUT-969 fixture's staff email
and password-variable declarations, with Infisical **dev `/application`**.
The root inner reader accepts exactly the four declared secret names; the
customer password, obsolete staff name, unrelated folder values and undeclared
names cannot be emitted. Other identities and Organisations matrices are kept.
Billing staff requires `platform_billing_manage` through the normal access API,
without acquiring Organisations permissions. The browser retains its origin,
receipt, readiness, real login, sentinel, leak, buffer and cleanup boundaries.

Implementation validation uses fictional values and simulated infrastructure
only. `uv run pytest tests/infra/test_dev_qa_credential_transport.py -q`:
**88 passed in 17.03 seconds**, no skips. Focused Ruff check passed. Tests bind
the transport to the fixture declarations, exercise pipe-only selection and
refusal for every identity, exclude other secrets, verify buffer zeroing after
success and failure, and require the billing grant from the normal API.

No live credential was read, fixture applied, refund requested or host/service
changed. Root install and non-root dev sentinel proof require reviewed, merged,
released artifacts. Actual sign-in, fixture data/settings and payment readback
remain on AUT-959; Root never performs Browser QA's single fictional refund.
