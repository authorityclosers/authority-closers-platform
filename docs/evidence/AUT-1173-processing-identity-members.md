# AUT-1173: exclude processing identities from organisation people

Base: `a0d537cf3c72a7734a18cbe7d913864f9254e7bd` (`main`).
Lane: `sx-org`, per the CEO's task amendment.

An organisation's processing service identity was included in the human member
directory. Its `processing` role fails the existing `MembersResponse` contract,
which accepts `owner`, `admin` and `member`.

The HTTP routes use `organisations.usage.member_rows`, so that query is filtered
alongside `OrganisationService.list_members`. The organisation profile, domain
settings response and platform organisation list now exclude processing
memberships from their member counts. Member-management queries also exclude
processing memberships before locking a target; the existing human-role guard
continues to refuse role changes, removal and ownership transfer with HTTP 404.

The API's JSON shapes stay the same. Human members and pending invitations retain
their existing visibility rules. The processing membership is preserved.

## Verification

The regression fixture has three fictional human members and one active
processing identity. Before the production changes, the new suite reported
`4 failed, 6 passed`: the service directory included the processing identity,
and the HTTP directories raised the reported `MembersResponse` validation error.

After the fix, the tests prove that both directories return the three humans,
all three member counts equal three, and owner/operator role, removal and
ownership-transfer requests against the processing identity return 404 without
changing any membership or adding an organisation audit event.

Commands run on the development checkout:

```sh
uv run ruff format --check packages/python tests
# 997 files already formatted
uv run ruff check packages/python tests
# All checks passed!
uv run mypy packages/python
# Success: no issues found in 417 source files
uv run pytest tests/unit/http/test_organisation_processing_identity.py tests/unit/http/test_organisation.py tests/unit/http/test_organisation_domains.py tests/unit/http/test_platform_organisations.py tests/unit/http/test_organisation_member_writes.py tests/unit/organisations -q
# 209 passed in 144.35s
ac-gate check
# ok: task/sx-org/1173-members-processing-filter may be worked on
git diff --check
# passed
```

PostgreSQL integration access is not configured in this session. HTTP checks use
the real FastAPI routes, canonical cookie authentication and fictional relational
fixtures on SQLite; they are not deployed-environment evidence.

## Dev and release checks

Run `uv run pytest tests/unit/http/test_organisation_processing_identity.py -q`
to reproduce the focused fixture. Once the reviewed build is available on dev
and staging, open Organisation → Members for a Sales Xray organisation with a
processing identity: the directory must load, list only humans, and show the
human count. Confirm the same behavior for staging AC before promoting the same
build through the approved release path and checking production EA.

CTO review, CEO approval, CI, merge and deployed verification remain release
requirements. This evidence records no production data change or promotion.
