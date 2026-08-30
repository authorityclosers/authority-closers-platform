# Staging Free Course seed

The learner preview currently contains static two-module/five-activity demo
content. The controlled direction is four modules, but the repository does not
contain authoritative four-module copy. The staging seed therefore has no
default payload and refuses to infer or promote the preview content.

Provide an explicit `free-course-staging-seed.v1` JSON document whose content
status is `reviewed`, whose topology contains exactly four modules and the five
approved activity kinds, and whose reviewed release ID matches the release
being seeded. The test-only fixture at
`tests/fixtures/free_course_staging_test_fixture.json` is not product content
and is accepted only by test application code.

The command is staging-only. `AC_RELEASE_ID` must be present in the release
environment and the reviewed document must carry the same 40-character
lowercase release SHA:

```powershell
uv run python scripts/seed_staging.py `
  --environment staging `
  --seed-data .\reviewed-free-course.json `
  --actor-person-id <existing-global-admin-person-id> `
  --release-id <40-character-lowercase-release-sha>
```

The `--actor-person-id` value must identify an existing active person with an
active `admin` or `owner` membership in an active tenant. The CLI does not
self-assert catalog permissions: the seed application verifies this persisted
authority in the same transaction and derives only the two narrowly required
catalog capabilities. The seed application is not registered as an HTTP route,
so a public learner/admin request cannot invoke this bootstrap path. This
prevents an arbitrary person ID or forged in-memory permission set from
granting global catalog write/publish authority; an authorized staging
operator remains responsible for supplying reviewed content.

It creates a deterministic stable program identity and deterministic IDs for
each content digest, publishes through the catalog application/domain paths,
and stores release ID, source reference, reviewer, review time, and SHA-256
content provenance on the immutable program version. An identical digest is a
no-op. Changed reviewed content creates and explicitly supersedes a new
version; an already-published version is never rewritten or republished.

The command prints only a non-sensitive seed receipt. The final staging smoke
must assert that anonymous `GET /v1/programs` returns a non-empty `items`
array, and that the returned version is the seeded immutable version. No
production invocation is supported.

## Temporary staging technical validation

Until the reviewed four-module source is supplied, the API release image can
exercise the catalog/enrollment/application seam with a separate synthetic
catalog. It is not Free Course content and is never accepted by `load_seed`.
Run this only from the API release image, with the staging environment already
bound to the canonical database:

```sh
test "${AC_ENVIRONMENT:-}" = staging
python -m ac_platform.seed \
  --technical-validation \
  --acknowledge-staging-technical-validation \
  --actor-person-id "$AC_SEED_ACTOR_PERSON_ID" \
  --release-id "$AC_RELEASE_ID"
```

The wheel includes `ac_platform.seed`, so this package-native command does not
depend on repository scripts or test files. It refuses unless
`AC_ENVIRONMENT=staging`, `AC_RELEASE_ID`, the acknowledgement flag, and a
real authorized actor are present; production is rejected unconditionally. The
actor ID must be the canonical `persons.id` of the first authenticated staging
admin/operator. Do not create a fixture person: if the ID is absent, inactive,
or lacks an active admin/owner membership, the command fails before catalog
writes. Obtain the ID from the authenticated admin's canonical session/context
or an approved staging database lookup.

The technical fixture uses the explicit slug
`staging-technical-validation` and title `STAGING-ONLY Technical Validation
Catalog`. It is deterministic and idempotent, stores release/content
provenance, and creates a new superseding version for changed content without
rewriting a published version. The resulting anonymous `GET /v1/programs`
response should contain this technical catalog, which is a staging plumbing
check only and must not be represented as an approved course release.
