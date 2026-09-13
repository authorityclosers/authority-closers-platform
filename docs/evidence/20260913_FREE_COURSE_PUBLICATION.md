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
canonical global slug. Existing staging identities are adopted using the
separate `adopt-existing` command. The owned Studio program supplies the upload
context only; its draft curriculum need not match the existing global course.
Adoption locks the exact global program, its current published version and its
complete module/activity/prerequisite graph. It independently validates that
target's reviewed provenance and canonical digest, then records
`catalog.free_course_adopted.v1` without changing catalog rows or learner
progress. Every supplied target UUID must match on replay. The source IDs in
this distinct receipt identify the upload context, not a curriculum derivation.

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

The publication result returns the deterministic global `video_activity_id`
alongside the program and version IDs. It deliberately returns
`media_status=pending_public_tenant_media_owner` until the separate media
promotion command runs. Media rows remain tenant-owned:
`media_assets.owner_person_id` and approved activity bindings both require an
active membership in the public learner tenant. The reviewed production owner
is Dipak (`033b7038-154a-4e5a-8a23-8d5ffeec2b4b`), who must be the authenticated
operator and must have active membership in the configured public tenant.

`FreeCourseMediaPromotionApplication` is the second, idempotent command. It
requires the publication receipt, the same operations actor, the target global
VIDEO activity, and one current READY source asset/version in the operations
tenant. One immutable `StudioVideoUpload` and its completed `MediaUploadIntent`
must bind those exact bytes to the receipt's source Studio program and owner;
ambiguous or unrelated admissions are refused before storage work. It verifies source checksum, object identity, processed rendition
inventory, and owner membership, then copies original and every object in
each validated HLS playlist/segment graph through the configured
private-storage port into deterministic public-tenant keys. Relative playlist
references are preserved and the complete target graph is revalidated before
READY. Copies are create-only; an exact existing target is reused on retry and
cleanup deletes only objects created by that attempt. It creates a new READY
public asset/version and calls the existing
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

For staging that already has an independently reviewed global course with pre-existing IDs,
record adoption instead of attempting a second publication. Supply the exact
IDs returned by the reviewed read-only inspection:

```text
printf '%s\n' "$COACH_SESSION_TOKEN" | uv run python -m ac_platform.catalog.cli adopt-existing \
  --environment staging \
  --source-program-id <verified-staging-owned-studio-program-uuid> \
  --program-id <existing-global-program-uuid> \
  --program-version-id <existing-global-version-uuid> \
  --video-activity-id <existing-global-video-activity-uuid> \
  --public-tenant-id <verified-staging-public-tenant-uuid> \
  --command-id <new-adoption-command-uuid> \
  --reason "Adopt the reviewed staging Free Course without changing progress"
```

Use the returned `program_id`, `program_version_id`, and
`video_activity_id`, together with the uploaded READY `source_asset_id` and
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

Validation record (supersedes the earlier six-test count):

- Publication, source-media provenance and CLI focused suite: 29 passed.
- Legacy adoption uses a separate one-module DRAFT upload context and an
  independently reviewed four-module GLOBAL course with distinct title,
  provenance and identities. All catalog/media rows are compared before/after.
- Changed program/version/video replay targets are refused. Invalid stored
  digest and missing/invalid review evidence are refused independently.
- Source-media provenance suite: 13 relational cases, included in the 29 above;
  exact admission, wrong program, missing/ambiguous admission and mismatched
  intent fields are exercised. Completed upload URL expiry is irrelevant.
- Ruff checks and focused mypy (three catalog sources) passed. The compatible
  local-avatar create-only adapter passed 42 avatar tests and package-wide
  mypy (198 sources).
- Actual PostgreSQL publication/promotion/HTTP and legacy-adoption CLI suite:
  `2 passed in 8.95s`. The separate owned database
  `ac_free_course_pgproof_full_20260913082617` was verified as owned by
  `ac_owner` and dropped after completion. This includes existing enrollment,
  progress and binding preservation with an independent four-module legacy
  target and one-module draft upload context.
- Independent review found no actionable P0/P1 in the final adoption rewrite.
  Historical replay returns only the same actor's immutable receipt after
  fresh platform/session authority; it does not claim a fresh source-course
  permission or mutate any content. No actual deployment is implied.

The opt-in PostgreSQL suite uses `AC_MEDIA_DELIVERY_RENEWAL_POSTGRES_TEST_URL`
(or `AC_TEST_DATABASE_URL`) and a disposable schema. No production database is
used for implementation tests. Existing source, progress, bindings and audit
history remain authoritative; deployment and actual video playback require
separate runtime receipts.
