# AUT-1694: verified self-serve organisation creation

`POST /v1/organisation` now accepts `{ "name": "Authority Closers" }` with a
canonical UUIDv4 `Idempotency-Key`, the normal session cookie, and a safe Origin.
It returns HTTP 201 with `tenant_id`, `handle`, `name` and `your_role: "owner"`.
The caller must be active with a verified email. The request cannot nominate a
different owner. It reuses `OrganisationService.create`, its transaction and
audit chain; the audit actor is the actual signed-in person.

The generated handle contains a bounded ASCII name prefix (or `organisation`
for a non-Latin name) and the complete random tenant UUID. It fits the existing
63-character unique slug column. A replay returns the same organisation;
changing the intent under the same command conflicts. Creation does not switch
the current workspace. The new organisation appears in `GET /v1/me/workspaces`
and can be selected through the existing context endpoint.

No billing account, seat grant, trial, usage or credit entry is created. Provider
acquisition approval and invite capacity remain separate gates. No schema,
identity-core, worker, payment, dependency or deployment changes are included in
this slice.

## Verification

`ac-heavy uv run pytest tests/unit/http/test_organisation_creation.py
tests/unit/organisations/test_service.py tests/unit/organisations/test_cli.py
tests/unit/http/test_organisation.py -q --tb=short`: **48 passed in 23.99s**.

Coverage includes verified and unverified people, expired/invalid authentication,
unsafe origins, malformed names, Hindi/Marathi names, no selected workspace,
safe unique handles, owner membership, person-attributed verifiable audit,
idempotent replay/conflict, unchanged selected context and no fabricated billing
capacity. Ruff check/format and `git diff --check` pass.

## Dev check after delivery

Sign in with a verified account in Personal. Submit the request above with a
fresh UUIDv4, select the returned tenant through the existing workspace switch,
and read `/v1/organisation/profile`. It should show the requested name and owner
role. Repeat the original create request with the same key: exactly one
organisation remains. Invitations and uploads are not asserted ready by this
slice; they still require the subsequent implementation and approved capacity.
