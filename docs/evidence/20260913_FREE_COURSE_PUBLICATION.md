# Free Course publication command — bounded source contract

Status: source implementation and disposable relational tests only. No VPS,
production database, media upload, learner enrollment, or runtime activation
was performed by this change.

`FreeCoursePublicationApplication` is the one-purpose bridge from Dipak's
operations-tenant Coach course to the learner catalog. It requires a current
authenticated session, both persisted platform capabilities
`platform_catalog_write` and `platform_catalog_publish`, the operations tenant
as the selected actor tenant, and source-course `catalog_publish` authority.
The configured public learner tenant must be active and distinct from
operations.

The command accepts a non-zero `command_id`, source program UUID, bounded
reason, and the exact approved public tenant UUID. It copies the latest draft
or published tenant version into the fixed global slug
`authority-closers-free-course` using deterministic descendant IDs. Source
modules, activities, prompts, required flags, prerequisites, and provenance
are copied through `AsyncCatalogApplication`; the source tenant rows are
preserved.

If the source is still a draft, the command requires all three review inputs:

- `source_ref`: the reviewed source or attribution reference, at most 500
  characters;
- `release_id`: the exact 40-character lowercase release SHA;
- `reviewed_at`: a timezone-aware review timestamp.

The reviewer is server-attributed to the authenticated person. The command
records `audit.catalog.version.reviewed.v1`, publishes the tenant version
through the existing catalog publication service, then records the global
publication receipt `catalog.free_course_published.v1`. A replay requires fresh
platform authority and the same source/public-tenant intent; it returns the
original IDs without creating rows. A different command ID cannot occupy the
canonical global slug, and an existing global course is never superseded by
this initial-slice command.

The reviewed runtime caller must resolve the authenticated Coach `ActorContext`
and execute the application inside its own transaction, for example:

```python
async with session.begin():
    result = await FreeCoursePublicationApplication(
        session,
        operations_tenant_id=OPS_TENANT_ID,
        public_tenant_id=PUBLIC_TENANT_ID,
    ).apply(
        actor=coach_actor,
        source_program_id=SOURCE_PROGRAM_ID,
        command_id=COMMAND_ID,
        reason="Approved initial public Free Course publication",
        source_ref="coach:dipak:big-buck-bunny-4k",
        release_id=RELEASE_SHA,
        reviewed_at=REVIEWED_AT,
    )
```

The caller commits only after checking the returned receipt. Reusing the same
command ID is safe and returns `status="replayed"`; changing the source or
public tenant with that ID is rejected.

The publication result deliberately returns
`media_status=pending_public_tenant_media_owner` until the separate media
promotion command runs. Media rows remain tenant-owned:
`media_assets.owner_person_id` and approved activity bindings both require an
active membership in the public learner tenant. The reviewed production owner
is Dipak (`033b7038-154a-4e5a-8a23-8d5ffeec2b4b`), who must be the authenticated
operator and must have active membership in the configured public tenant.

`FreeCourseMediaPromotionApplication` is the second, idempotent command. It
requires the publication receipt, the same operations actor, the target global
VIDEO activity, and one current READY source asset/version in the operations
tenant. It verifies source checksum, object identity, processed rendition
inventory, and owner membership, then copies original and rendition objects
through the configured private-storage port into deterministic public-tenant
keys. It creates a new READY public asset/version and calls the existing
`MediaService.bind_activity_media` ledger through a sealed internal
authorization. An optional `supersedes_binding_id` explicitly replaces the
current public-tenant binding and leaves learner progress and the prior audit
row intact. Captions are refused until a separately reviewed target caption
contract exists.

The source READY lifecycle remains the ordinary authenticated Coach upload,
ClamAV scan, FFmpeg processing, and completion path. The promotion command
does not read a filesystem path, bypass scanning, mutate the source asset, or
copy rows through SQL. It is safe to retry with the same command IDs.

The production operator entry point is `python -m ac_platform.catalog.cli`.
It reads the existing session token from hidden terminal input (or stdin when
the operator deliberately pipes it), never accepts a token as a command-line
argument, and prints only the non-secret receipt. The release profile must
already have `AC_MEDIA_FILESYSTEM_ENABLED=true` and its reviewed private
storage/scanner paths. First publish the Coach draft (the supplied IDs are
source program `a1993f11-f43d-446a-821f-550bc40b950c`, operations tenant
`fb594dea-fdb6-444c-a36f-1d94fbc65bbf`, public tenant
`c1d51741-6e0f-4ddc-8cc4-58856d0e778f`):

```text
printf '%s\n' "$COACH_SESSION_TOKEN" | uv run python -m ac_platform.catalog.cli publish \
  --environment production --allow-production \
  --source-program-id a1993f11-f43d-446a-821f-550bc40b950c \
  --public-tenant-id c1d51741-6e0f-4ddc-8cc4-58856d0e778f \
  --command-id <new-publication-command-uuid> \
  --reason "Dipak approved the reviewed Authority Closers free course" \
  --source-ref coach:dipak:big-buck-bunny-4k \
  --release-id <exact-40-character-release-sha> \
  --reviewed-at <timezone-aware-review-timestamp>
```

Use the returned `program_id`, `program_version_id`, and VIDEO
`activity_id`, together with the uploaded READY `source_asset_id` and
`source_version_id`, for the second command. Pass the current public binding ID
as `--supersedes-binding-id` when replacing staging media; omit it for the
empty production tenant:

```text
printf '%s\n' "$COACH_SESSION_TOKEN" | uv run python -m ac_platform.catalog.cli promote-media \
  --environment production --allow-production \
  --public-tenant-id c1d51741-6e0f-4ddc-8cc4-58856d0e778f \
  --publication-command-id <publication-command-uuid> \
  --command-id <new-media-promotion-command-uuid> \
  --activity-id <published-global-video-activity-uuid> \
  --source-asset-id <ready-operations-asset-uuid> \
  --source-version-id <ready-operations-version-uuid> \
  --media-owner-person-id 033b7038-154a-4e5a-8a23-8d5ffeec2b4b \
  --approval-reference AC-FREE-COURSE-PROMOTION:<change-reference>
```

Focused evidence:

```text
uv run pytest -q tests/unit/catalog/test_free_course_publication.py
6 passed
uv run ruff check packages/python/ac_platform/catalog/free_course_publication.py \
  packages/python/ac_platform/catalog/__init__.py \
  tests/unit/catalog/test_free_course_publication.py
All checks passed
uv run mypy --config-file pyproject.toml \
  packages/python/ac_platform/catalog/free_course_publication.py \
  packages/python/ac_platform/catalog/free_course_media.py \
  packages/python/ac_platform/catalog/cli.py
Success: no issues found in 4 source files
```

The tests cover an idempotent publication replay, preservation of the tenant
source, cross-tenant actor denial, missing review evidence, draft review and
publish, command-ID intent conflict, refusal to replace an existing global
course, READY source checksum/rendition checks, public-tenant asset creation,
binding, replay, and explicit supersession of an existing global binding.
