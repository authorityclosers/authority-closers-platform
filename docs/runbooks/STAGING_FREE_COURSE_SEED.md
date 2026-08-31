# Staging Free Course seed

The release wheel contains the controlled v0.1 topology foundation selected by
`--controlled-foundation-v1`. Its source is the controlled AC-IMP-04 decision
baseline. It contains the exact four approved shift titles and only the first
production slice of the learning workflow:

1. Module 1 has the complete `VIDEO -> REFLECTION ->
   IMPLEMENTATION_CHALLENGE -> REVIEW -> IMPROVE` loop.
2. Modules 2–4 preserve the approved four-shift topology and sequential
   prerequisites but intentionally contain no activities. They are extension
   contracts, not claims that the future course has been delivered.

The short activity prompts are bounded workflow scaffolding for the implemented
loop. They are not a claim that final teaching copy, video, transcript,
resources, or later-module content has been approved.

The packaged JSON carries the literal `$AC_RELEASE_ID` placeholder. The loader
resolves it only for staging/test and only to the exact baked 40-character
release SHA. Production seed invocation remains unsupported.

## Apply the controlled foundation

Run from the exact API release image after migrations and before learner smoke
testing:

```sh
test "${AC_ENVIRONMENT:-}" = staging
python -m ac_platform.seed \
  --controlled-foundation-v1 \
  --actor-person-id "$AC_SEED_ACTOR_PERSON_ID" \
  --release-id "$AC_RELEASE_ID"
```

`AC_SEED_ACTOR_PERSON_ID` must be the canonical `persons.id` for an existing,
active staging person with an active `admin` or `owner` membership in an active
tenant. Obtain it from the authenticated operator's canonical session/context
or an approved read-only staging lookup. Never create a fixture person and
never use direct SQL to create or repair course state.

The CLI verifies persisted authority in the same transaction and derives only
the two narrowly required catalog capabilities. It is not an HTTP route, so a
learner/admin browser request cannot invoke the bootstrap path. The command
fails closed when its environment, baked release, supplied release, actor, or
controlled payload does not match.

The application creates a deterministic stable program identity and
deterministic IDs for each content digest. It publishes through the catalog
application/domain path and stores release ID, exact Drive source reference,
review authority/time, and SHA-256 content provenance on the immutable program
version. An identical digest is a no-op. A changed reviewed digest creates and
supersedes a new version; a published version is never rewritten.

The command prints only a non-sensitive receipt. After application, prove:

- a second identical application is an idempotent no-op;
- anonymous `GET /v1/programs` returns the controlled program/version;
- Module 1 exposes exactly the five ordered activity kinds;
- Modules 2–4 expose no activities and remain sequentially locked;
- an authenticated learner is enrolled through the application API, not by
  direct database edits.

## Explicit external reviewed payload

`--seed-data <path>` remains available for a future reviewed
`free-course-staging-seed.v1` document. It cannot be combined with
`--controlled-foundation-v1`; the same source, review, topology, activity-kind,
environment, release, and immutable-history checks apply.

## Synthetic technical validation

`--technical-validation --acknowledge-staging-technical-validation` remains a
separate staging-only plumbing fixture. It is not Free Course content and must
not be represented as an approved course release. Prefer the controlled
foundation for v0.1 acceptance; use the synthetic fixture only when diagnosing
the catalog/enrollment seam independently of product content.
