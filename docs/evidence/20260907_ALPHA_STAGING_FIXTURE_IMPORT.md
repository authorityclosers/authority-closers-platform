# Alpha staging public-film import — 2026-09-07

## Outcome and boundary

The package-owned import path can publish a new technical catalog revision and
atomically register, process and approve the two licensed film excerpts. It
does not activate uploads, S3, webhooks, real instructional media, enrollment,
progress, payment, or production delivery. No VPS or persistent application
database was changed for this evidence.

The two VIDEO activity titles and authored learner prompts explicitly say
STAGING TEST ONLY, 12-second technical excerpt, not Dipak instruction. Prompts
contain film credits, Creative Commons license URLs, official source URLs,
the transcode/remux modification notice, and the warning that captions are
synthetic player-test cues rather than film dialogue. Credits are canonical
catalog content, not a frontend UUID lookup or audit-only metadata.

The package-owned v2 builder retains the original technical program identity,
publishes a distinct immutable content version through `StagingSeedApplication`,
and preserves old enrollments and old version history. The original v1 fixture
and strict external seed loader are unchanged. It does not bind films to any
actual Dipak instructional activity.

## Exact artifact and contract

Package manifest: `ac_platform/media/data/alpha_public_films_12s_v1.json`.

- Manifest SHA-256: `d693acc73dc3f66c1b13ad6e68d5e41cba8478dc719f4b68211ce829442b0222`.
- Original fixture registry SHA-256: `fc61c87d5428d53d35b82061a53fbdbd9967b8bf658c6d0425a78a07bc106290`.
- New catalog content UUID: `25e49751-f0a2-5642-aae9-b7ad0019ab34`.
- Local ignored pack: `tools/media-player-stress/.artifacts/staging-alpha-public-films-12s-v1/`.
- 30 explicitly enumerated files; no glob-based authorization or external manifest input.

| Excerpt | Measured video | Video / audio-container timeline | Progressive SHA-256 |
| --- | --- | --- | --- |
| Big Buck Bunny, Sunflower | 3840×2160, H264/AAC, 30 fps | 12.000 / 12.032 seconds | `7e7ee255d0ca2866ad528e9d6ddc0049a66883d6984ea9bf4d9fed188907bd4a` |
| Caminandes 2: Gran Dillama | 1920×1080, H264/AAC, 24 fps | 12.000 / 12.032 seconds | `a85f27d1b52848fb51c486a882e2bd61318da502b62d7537e81ecca739198d74` |

The 32 ms AAC padding is retained, not rounded away. Source video is exactly
12 seconds; accepted AV/HLS timeline difference is at most 50 ms. The manifest
uses the measured container duration, 12.032 seconds. BBB HLS includes 2160p,
1080p and 360p; Caminandes includes 1080p and 360p. Each video variant has three
4-second segments. Progressive MP4 is a local copy/remux of the highest-quality
HLS rendition, not a second unverified source.

The manifest pins full-source provenance hashes from the original fixture
registry, per-file hashes and sizes, probe hashes, exact paths and MIME types.
The loader also checks probe codec/dimensions/frame-rate/timelines, MP4 file
signature, exact reachable HLS graph, VTT inventory, and storage byte integrity.
`ReadOnlyFileMediaStorage` supplies only explicitly mapped immutable objects.
An OS read-only mount is still required; this is not a sandbox against an OS
administrator who can replace both trusted deployment code and artifacts.

## Application invariants

1. Production and non-staging/test environments fail before filesystem or DB
   setup. Staging requires the exact baked 40-character release identity.
2. Only the package-owned manifest and compiled expected digest are accepted.
   The command has no source URL, arbitrary manifest/path inventory, caller
   media metadata, READY flag, attestation string or playback-grant input.
3. Every source, probe and HLS inventory is revalidated before the import DB
   transaction. Selected tenant and release must match the verified package.
4. Persisted active person, active exact tenant, and active unended admin/owner
   membership are checked and locked. Caller permission strings do not confer
   authority. Catalog publication rechecks exact tenant membership inside the
   canonical seed transaction, including on replay.
5. The exact published global technical-media version, its immutable provenance,
   and the two authored VIDEO identities/titles/prompts must match.
6. The source-registration method writes PROCESSING only. Existing
   `MediaService.process_version` performs final source, quota, measured
   duration, rendition, caption and complete HLS graph checks before READY.
7. Existing `bind_activity_media` approves each exact activity/version under an
   explicit public-film approval reference and deterministic idempotency key.
   Existing bindings are never silently superseded, reactivated or repaired.
8. Both films, processing results, bindings and one attributable hash-chain
   audit event commit together or roll back together. The audit stores the
   real operator person and `session_id=None`; no fabricated browser-session FK.
9. Replay for the same approved tenant/operator/release/catalog/manifest returns
   the same IDs. It verifies READY metadata, asset current version, exact
   rendition/caption inventory, approved binding and audit identities. Changed,
   revoked, partial or occupied state is a conflict, not a recovery mutation.
10. PostgreSQL row locks and an explicit tenant advisory lock serialize import
    identity. The local SQLite tests do not establish PostgreSQL concurrency
    performance or deployment acceptance.

## Operator entry points (not executed against VPS)

Use the deployed application container and its existing environment. Substitute
only the existing authorized person, configured learner tenant, and exact baked
release; do not generate new tenant IDs or edit database rows manually.

Publish the separately labeled catalog revision:

```sh
python -m ac_platform.media.staging_fixture_import \
  --actor-person-id <existing-admin-person> \
  --tenant-id <configured-existing-learner-tenant> \
  --release-id <exact-baked-release-sha> \
  --publish-catalog \
  --acknowledge-staging-public-film-tests
```

After the reviewed pack is mounted read-only at the explicitly configured
fixture cache root, import its two films:

```sh
python -m ac_platform.media.staging_fixture_import \
  --actor-person-id <same-existing-admin-person> \
  --tenant-id <configured-existing-learner-tenant> \
  --release-id <same-exact-baked-release-sha> \
  --catalog-version-id 25e49751-f0a2-5642-aae9-b7ad0019ab34 \
  --manifest-sha256 d693acc73dc3f66c1b13ad6e68d5e41cba8478dc719f4b68211ce829442b0222 \
  --acknowledge-staging-public-film-tests
```

Import requires `AC_ENVIRONMENT=staging`, matching `AC_RELEASE_ID`, the existing
`AC_PUBLIC_LEARNER_TENANT_ID`, explicit `AC_MEDIA_STRESS_FIXTURES_ENABLED`, and
`AC_MEDIA_STRESS_FIXTURES_CACHE_ROOT`. Publication alone requires no media files.
These flags do not by themselves mount learner delivery. Runtime delivery is a
separately reviewed fixture-only opt-in, with same-origin signed routes and
persisted request/session/access authorization. General provider activation
remains disabled. The operator CLI emits only status and identity/provenance
metadata, not signed URLs, secrets or credentials.

## Verification

Executed locally in the implementation lane:

```text
uv run pytest tests/unit/media/test_staging_fixture_import.py \
  tests/unit/media/test_activity_delivery_authorization.py tests/unit/seed -q
115 passed, 1 existing Starlette TestClient deprecation warning (27.91s)

uv run mypy packages/python/ac_platform/media/staging_fixture_manifest.py \
  packages/python/ac_platform/media/staging_fixture_import.py \
  packages/python/ac_platform/seed/technical_media_fixture_v2.py \
  packages/python/ac_platform/media/service.py
Success: no issues found in 4 source files
```

Ruff checks passed for those four implementation files and the new import test
file. The 49 new tests use hermetic structural byte doubles plus real SQLite
ORM transactions, savepoints and enabled foreign keys. They verify positive
import/replay, retained old enrollment, credits, exact tenant authority,
pre-transaction changed-source denial, source PROCESSING-only registration,
catalog identity, malformed manifest/probe/HLS denial, later processing/binding/
audit failure rollback, partial-state refusal and revoked/drifted replay denial.
These doubles are not real video decode evidence and are not available through
the deployed CLI.

A separate local real-byte check loaded the actual ignored package and used
the same canonical seed/import applications in an ephemeral SQLite database
with foreign keys enabled. Result:

```json
{
  "isolated_real_pack_import": "imported",
  "replay": "already_imported",
  "ready": [[3840, 2160, 12.032], [1920, 1080, 12.032]],
  "binding_count": 2,
  "audit_chain_valid": true,
  "manifest_sha256": "d693acc73dc3f66c1b13ad6e68d5e41cba8478dc719f4b68211ce829442b0222"
}
```

GET and HEAD signed delivery routes also now have distinct explicit OpenAPI
operation IDs; the focused HTTP behavior test verifies both identities.

Still required for Alpha's live media claim: reviewed runtime composition,
read-only VPS mount and application-command results, canonical learner access
to the new version, authenticated same-origin MP4 Range/HEAD and HLS child
requests, copied/expired/revoked URL denial, visible source credits, captions,
quality/control/mobile browser checks, and resource/concurrency evidence.
No local fixture or SQLite result is presented as VPS streaming acceptance.

## PostgreSQL acceptance added; local execution unavailable

`tests/integration/test_staging_fixture_import_postgresql.py` adds 12 acceptance
cases using real `AsyncSession` connections, the existing guarded
`AC_TEST_DATABASE_URL` integration target, and the staging seed's disposable
Alembic-migrated PostgreSQL schema. It reuses only the hermetic pytest package
fixture; the deployed manifest/CLI contract remains unchanged.

The cases exercise same-actor replay, three concurrent import attempts yielding
one import and two identical replays, two different administrators competing
without approval/audit reassignment, the exact tenant advisory lock blocking
until its owning transaction commits, rollback on second-film processing or
binding failure and final audit failure, plus learner/other-tenant/inactive
membership/person/tenant denial. Races have bounded waits and cancel/drain
unfinished sibling tasks so failed tests do not leave open transactions.

Executed locally:

```text
uv run pytest tests/integration/test_staging_fixture_import_postgresql.py -q
12 skipped in 3.28s: staging seed PostgreSQL URL is not configured
```

Ruff and `git diff --check` pass. No PostgreSQL URL was configured in the local
session, so PostgreSQL transaction/concurrency acceptance is **pending**, not
passed. Existing `.github/workflows/application.yml` supplies a local PostgreSQL
service URL and runs the full `uv run pytest` suite; this new file will execute
there when the candidate is submitted. No workflow or remote database was
modified by this task.

Independent review of the core import/manifest/seed/source-registration changes
reported no Critical/Important finding, independently passed all 49 new unit
tests, and verified the actual 30-object, 54,274,209-byte package. That review
does not substitute for the pending PostgreSQL or deployed-browser checks.
