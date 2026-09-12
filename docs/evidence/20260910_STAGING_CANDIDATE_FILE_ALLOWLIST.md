# Staging candidate file allowlist — 2026-09-10

Status: read-only tree inventory plus this evidence file. No file was staged,
committed, switched, deployed or used to change a service. Secrets were not
read. The comparison base is the last evidenced staging commit
`4e8d413b828ab750d7c5e20d1a9320d0f427c823`; the working-tree HEAD is
`7bdd069d4bf00561edcab90b1679666205708185`.

## Exact snapshot

Snapshot time before this document was added: `2026-09-10T14:23:15+05:30`.
Adding this document changes only the untracked/status totals shown in the last
two rows.

| Measure | Count |
| --- | ---: |
| Files in the staging commit | 1,873 |
| Staging files still present in the working tree | 1,873 |
| Staging files absent from the working tree | 0 |
| Working files byte-identical to staging | 1,796 |
| Working files advanced from staging | 77 |
| HEAD-to-staging delta paths | 66 |
| HEAD-to-staging paths preserved exactly | 41 |
| HEAD-to-staging paths advanced further | 25 |
| HEAD-to-staging paths missing or reverted to HEAD | 0 |
| Modified tracked paths | 88 |
| Untracked, non-ignored paths before this document | 1,278 |
| Untracked, non-ignored paths after this document | 1,279 |
| `git status --porcelain=v1` entries after this document | 319 |

The 77 changed staging files are candidate deltas, not automatically
regressions. They require final integrated review. Blob comparison found no
missing staging file and no staging delta reverted to `7bdd069d`.

## Allowlist summary

The candidate delta allowlist contains **251 paths**:

| Disposition | Count |
| --- | ---: |
| Exact staging carry-forward required because this worktree starts at the older HEAD | 41 |
| Existing staging files advanced by the candidate | 77 |
| Truly new code, runtime assets, QA tooling and tests | 111 |
| New or post-deployment Markdown evidence, including this manifest | 12 |
| Curated candidate screenshot/proof pack | 10 |

The untracked portion is **163 allowlisted paths** and **1,116 excluded paths**.
Do not use `git add -A`; stage only the explicit groups below.

## Exact staging carry-forward — 41

These files are byte-identical to staging but dirty or untracked relative to the
older local HEAD. They must be retained when reconstructing a candidate from
this worktree.

```text
apps/admin-web/app/components/admin-session-refresh.test.tsx
apps/admin-web/app/components/operations-login.test.tsx
apps/admin-web/app/lib/admin-api.test.ts
apps/coach-web/app/components/coach-preferences.tsx
apps/coach-web/app/components/coach-settings.tsx
apps/coach-web/app/components/coach-shell.tsx
apps/coach-web/app/components/coach-workspace.test.tsx
apps/coach-web/app/layout.tsx
apps/coach-web/app/page.tsx
apps/coach-web/app/studio/layout.tsx
apps/coach-web/app/studio/page.tsx
apps/coach-web/app/studio/programs/[programId]/page.tsx
apps/coach-web/app/studio/programs/page.tsx
apps/coach-web/app/studio/publication/page.tsx
apps/coach-web/app/studio/settings/page.tsx
apps/coach-web/app/styles.css
apps/coach-web/vitest.config.mjs
apps/learner-web/app/lib/community-api.test.ts
apps/learner-web/app/lib/learner-api.ts
apps/learner-web/app/lib/revenue-journey-resume.acceptance.test.ts
apps/learner-web/app/theme.css
db/migrations/versions/20260909_0024_studio_media_library_index.py
db/migrations/versions/20260909_0025_studio_course_creation.py
db/migrations/versions/20260910_0026_studio_video_uploads.py
db/migrations/versions/20260910_0027_academy_public_profiles.py
docs/evidence/20260908_PRACTICE_TENANT_PILOT_GATING.md
docs/evidence/20260910_STAGING_OFFSITE_RESTORE_ACCEPTANCE.md
infra/application/environments/staging.env
infra/application/scripts/install-application-release.sh
packages/python/ac_platform/catalog/models.py
packages/python/ac_platform/db/models.py
packages/python/ac_platform/media/models.py
packages/typescript/operations-web/package.json
packages/typescript/operations-web/src/admin-session.tsx
packages/typescript/operations-web/src/operations-login.tsx
packages/typescript/operations-web/src/studio/studio-workspace.module.css
tests/infra/test_admin_internal_transport.py
tests/infra/test_application_release.py
tests/infra/test_public_films.py
tests/infra/test_staging_public_films.py
tests/unit/community/test_username_policy.py
```

Of the 30 currently untracked files already present in staging, 17 are in this
exact-carry-forward list. The other 13 are in the advanced list below:

```text
apps/learner-web/app/components/community-identity-card.module.css
apps/learner-web/app/components/community-identity-card.test.tsx
apps/learner-web/app/components/community-identity-card.tsx
docs/evidence/20260910_ACADEMY_COMMUNITY_IDENTITY_CANDIDATE.md
docs/evidence/20260910_COACH_WORKSPACE.md
packages/python/ac_platform/community/__init__.py
packages/python/ac_platform/community/application.py
packages/python/ac_platform/community/models.py
packages/python/ac_platform/http/community.py
packages/typescript/operations-web/src/studio/studio-workspace.tsx
tests/integration/test_community_identity_postgresql.py
tests/unit/community/test_application.py
tests/unit/http/test_community_routes.py
```

## Existing staging files advanced — 77

These exact paths differ from staging and form the review surface for changes to
already deployed files.

```text
apps/admin-web/app/components/studio/studio-course-editor.test.tsx
apps/admin-web/app/lib/dev-api-proxy.test.ts
apps/learner-web/app/components/community-identity-card.module.css
apps/learner-web/app/components/community-identity-card.test.tsx
apps/learner-web/app/components/community-identity-card.tsx
apps/learner-web/app/components/learner-runtime.tsx
apps/learner-web/app/components/learning-course-card.tsx
apps/learner-web/app/components/learning-journey.module.css
apps/learner-web/app/components/learning-runtime.tsx
apps/learner-web/app/components/practice-arcade.module.css
apps/learner-web/app/components/practice-arcade.test.tsx
apps/learner-web/app/components/practice-arcade.tsx
apps/learner-web/app/components/practice-companion-stage.module.css
apps/learner-web/app/components/practice-companion-stage.tsx
apps/learner-web/app/components/practice-engine.module.css
apps/learner-web/app/components/practice-engine.test.tsx
apps/learner-web/app/components/practice-engine.tsx
apps/learner-web/app/components/practice-sound-controls.module.css
apps/learner-web/app/components/practice-sound-controls.test.tsx
apps/learner-web/app/components/practice-sound-controls.tsx
apps/learner-web/app/components/profile-runtime.tsx
apps/learner-web/app/components/shared-practice-presentation.test.tsx
apps/learner-web/app/course-surfaces.css
apps/learner-web/app/lib/avatar-upload.test.ts
apps/learner-web/app/lib/avatar-upload.ts
apps/learner-web/app/lib/learner-course-surfaces.test.ts
apps/learner-web/app/lib/learner-ui.test.ts
apps/learner-web/app/lib/practice-sounds.test.ts
apps/learner-web/app/lib/practice-sounds.ts
apps/learner-web/public/audio/practice/LICENSE.md
apps/learner-web/public/audio/practice/manifest.json
docs/evidence/20260910_ACADEMY_COMMUNITY_IDENTITY_CANDIDATE.md
docs/evidence/20260910_COACH_WORKSPACE.md
infra/application/scripts/restore-drill.py
infra/vps-foundation/scripts/ac-postgres-backup.py
infra/vps-foundation/scripts/ac-restic-postgres-restore-proof.py
packages/python/ac_platform/catalog/services.py
packages/python/ac_platform/community/__init__.py
packages/python/ac_platform/community/application.py
packages/python/ac_platform/community/models.py
packages/python/ac_platform/http/admin_learning.py
packages/python/ac_platform/http/app.py
packages/python/ac_platform/http/community.py
packages/python/ac_platform/http/request_limits.py
packages/python/ac_platform/http/surfaces.py
packages/python/ac_platform/media/delivery.py
packages/python/ac_platform/media/local_avatar_runtime.py
packages/python/ac_platform/media/processing.py
packages/python/ac_platform/media/runtime.py
packages/python/ac_platform/media/service.py
packages/python/ac_platform/media/storage.py
packages/python/ac_platform/outbox/repository.py
packages/python/ac_platform/worker/__init__.py
packages/typescript/operations-web/src/admin-api.ts
packages/typescript/operations-web/src/dev-api-proxy.ts
packages/typescript/operations-web/src/studio/studio-course-editor.module.css
packages/typescript/operations-web/src/studio/studio-course-editor.tsx
packages/typescript/operations-web/src/studio/studio-runtime.tsx
packages/typescript/operations-web/src/studio/studio-workspace.tsx
packages/typescript/ui/package.json
packages/typescript/ui/src/interaction-primitives.tsx
scripts/Start-LocalApi.ps1
scripts/Start-LocalPlatform.ps1
scripts/Start-LocalPostgres.ps1
tests/database/test_catalog.py
tests/database/test_model_registry.py
tests/infra/test_capability_backup_parity.py
tests/integration/test_community_identity_postgresql.py
tests/unit/community/test_application.py
tests/unit/http/test_coach_surface.py
tests/unit/http/test_community_routes.py
tests/unit/media/test_media_delivery_phase2.py
tests/unit/media/test_provider_foundation.py
tests/unit/outbox/test_jobs.py
tests/unit/test_local_platform_launcher.py
tests/unit/test_practice_audio_assets.py
tests/unit/worker/test_worker.py
```

Twenty-five of these also advance files introduced or changed by the deployed
staging delta. That overlap is expected and must receive three-way review
against both `7bdd069d` and `4e8d413b`.

## Truly new code, assets, tooling and tests — 111

All paths below are new relative to staging. Counts are exact.

### Application files — 21

```text
apps/admin-web/app/components/studio/studio-course-create.test.tsx
apps/admin-web/app/components/studio/studio-video-upload.test.tsx
apps/admin-web/app/lib/local-studio-video-transport.test.ts
apps/admin-web/app/lib/studio-course-create-api.test.ts
apps/admin-web/app/lib/studio-video-upload-api.test.ts
apps/admin-web/app/lib/studio-video-upload-proxy.test.ts
apps/admin-web/app/lib/studio-video-upload-session.test.ts
apps/learner-web/app/components/academy-leaderboard.module.css
apps/learner-web/app/components/academy-leaderboard.test.tsx
apps/learner-web/app/components/academy-leaderboard.tsx
apps/learner-web/app/components/practice-art.tsx
apps/learner-web/app/components/practice-brief.tsx
apps/learner-web/app/components/practice-rewards.module.css
apps/learner-web/app/components/practice-rewards.tsx
apps/learner-web/app/leaderboard/page.tsx
apps/learner-web/app/lib/practice-music.test.ts
apps/learner-web/app/lib/practice-music.ts
apps/learner-web/public/audio/practice/MUSIC_LICENSE.md
apps/learner-web/public/audio/practice/music-manifest.json
apps/learner-web/public/audio/practice/overworld-loop.mp3
apps/learner-web/public/audio/practice/retry.wav
```

The four new audio files must remain a single provenance-bound unit with the
updated `LICENSE.md`, `manifest.json`, `practice-sounds.*` and audio tests. No
subjective audio approval is inferred.

### Schema and operational source — 5

```text
db/migrations/versions/20260910_0028_global_community_identity.py
infra/media-safety/clamd.conf
infra/media-safety/compose.yaml
infra/media-safety/freshclam.conf
infra/media-safety/manage.py
```

Global Cohorva username separate from academy leaderboard is approved. The
exact reserved-name set and an isolated staging-data collision rehearsal remain
release gates. `infra/media-safety` is source for a separate private scanner
pilot; including it does not activate or deploy that service.

### Python and TypeScript packages — 31

```text
packages/python/ac_platform/development/studio_video_app.py
packages/python/ac_platform/http/studio_media.py
packages/python/ac_platform/http/studio_video_bytes.py
packages/python/ac_platform/media/clamav_scanner.py
packages/python/ac_platform/media/studio_contract.py
packages/python/ac_platform/media/studio_library.py
packages/python/ac_platform/media/studio_selection.py
packages/python/ac_platform/media/studio_upload.py
packages/python/ac_platform/media/studio_video_completion.py
packages/python/ac_platform/media/studio_video_delivery.py
packages/python/ac_platform/media/studio_video_processing.py
packages/python/ac_platform/media/studio_video_runner.py
packages/python/ac_platform/media/studio_video_runtime.py
packages/python/ac_platform/media/studio_video_worker.py
packages/python/ac_platform/media/video_file_storage.py
packages/python/ac_platform/media/video_probe.py
packages/typescript/operations-web/src/local-studio-video-transport.ts
packages/typescript/operations-web/src/studio/studio-course-create.module.css
packages/typescript/operations-web/src/studio/studio-course-create.tsx
packages/typescript/operations-web/src/studio/studio-lesson-type-picker.module.css
packages/typescript/operations-web/src/studio/studio-lesson-type-picker.tsx
packages/typescript/operations-web/src/studio/studio-video-api.test.ts
packages/typescript/operations-web/src/studio/studio-video-api.ts
packages/typescript/operations-web/src/studio/studio-video-panel.module.css
packages/typescript/operations-web/src/studio/studio-video-panel.test.tsx
packages/typescript/operations-web/src/studio/studio-video-panel.tsx
packages/typescript/operations-web/src/studio/studio-video-upload-api.ts
packages/typescript/operations-web/src/studio/studio-video-upload-session.ts
packages/typescript/operations-web/src/studio/studio-video-upload.module.css
packages/typescript/operations-web/src/studio/studio-video-upload.tsx
packages/typescript/ui/src/blob-sha256.ts
```

### Local QA/runtime tooling — 7

```text
scripts/Get-LocalTcpListeners.ps1
scripts/Local-RuntimeBootstrap.ps1
scripts/Start-LocalStudioVideoScanner.ps1
scripts/inspect-local-studio-video.py
scripts/prove-local-arcade-feedback.py
scripts/prove-local-profile-photo.py
scripts/prove-local-studio-video-upload.py
```

These are implementation/acceptance tooling, not permission to activate a VPS
scanner or upload capability.

### Tests — 47

```text
tests/infra/test_local_tcp_listeners.py
tests/infra/test_media_safety.py
tests/integration/test_ffmpeg_video_attempts.py
tests/integration/test_ffmpeg_video_metadata.py
tests/integration/test_job_kind_isolation_postgresql.py
tests/integration/test_studio_course_creation_postgresql.py
tests/integration/test_studio_library_postgresql.py
tests/integration/test_studio_selection_postgresql.py
tests/integration/test_studio_video_bytes_postgresql.py
tests/integration/test_studio_video_completion_postgresql.py
tests/integration/test_studio_video_pipeline_postgresql.py
tests/integration/test_studio_video_playback_journey_postgresql.py
tests/integration/test_studio_video_ready_postgresql.py
tests/integration/test_studio_video_runtime_postgresql.py
tests/integration/test_studio_video_upload_issuer_postgresql.py
tests/integration/test_studio_video_upload_postgresql.py
tests/integration/test_studio_video_worker_fence_postgresql.py
tests/unit/development/test_studio_video_app.py
tests/unit/http/test_studio_course_creation.py
tests/unit/http/test_studio_media.py
tests/unit/http/test_studio_media_composition.py
tests/unit/http/test_studio_video_bytes.py
tests/unit/http/test_studio_video_capability.py
tests/unit/http/test_studio_video_completion_http.py
tests/unit/http/test_studio_video_runtime_app.py
tests/unit/http/test_studio_video_upload.py
tests/unit/media/test_clamav_scanner.py
tests/unit/media/test_studio_contract.py
tests/unit/media/test_studio_library.py
tests/unit/media/test_studio_selection.py
tests/unit/media/test_studio_upload.py
tests/unit/media/test_studio_video_completion.py
tests/unit/media/test_studio_video_delivery.py
tests/unit/media/test_studio_video_processing.py
tests/unit/media/test_studio_video_runner.py
tests/unit/media/test_studio_video_runtime.py
tests/unit/media/test_studio_video_upload_issuer.py
tests/unit/media/test_studio_video_worker.py
tests/unit/media/test_video_batch_verification.py
tests/unit/media/test_video_file_storage.py
tests/unit/media/test_video_output_streaming.py
tests/unit/media/test_video_probe.py
tests/unit/media/test_video_processing_attempts.py
tests/unit/media/test_video_processing_metadata.py
tests/unit/media/test_video_source_streaming.py
tests/unit/test_local_runtime_bootstrap.py
tests/unit/test_practice_music_asset.py
```

## New Markdown evidence — 12

```text
docs/evidence/20260909_STUDIO_COURSE_CREATION.md
docs/evidence/20260909_STUDIO_VIDEO_APPROVAL.md
docs/evidence/20260909_VIDEO_PROCESSING_GEOMETRY.md
docs/evidence/20260910_LOCAL_MEDIA_SAFETY.md
docs/evidence/20260910_LOCAL_STARTUP_RECOVERY.md
docs/evidence/20260910_PRACTICE_LIBRARY_CLARITY.md
docs/evidence/20260910_REVENUE_JOURNEY_RESUME_ACCEPTANCE.md
docs/evidence/20260910_STAGING_ARCADE_ACTIVATION_ACCEPTANCE.md
docs/evidence/20260910_STAGING_CANDIDATE_FILE_ALLOWLIST.md
docs/evidence/20260910_STUDIO_VIDEO_UPLOAD_PIPELINE.md
docs/product/V02_REVENUE_RELEASE_CUT.md
docs/runbooks/LOCAL_THREE_APP_STARTUP.md
```

These documents contain local evidence and bounded claims. References to
ignored `.tmp` proofs do not make those transient files release inputs.

## Curated screenshot/proof pack — 10

Only this current candidate pack is allowlisted from the 1,125 untracked files
under `docs/evidence/screenshots`:

```text
docs/evidence/screenshots/studio-video-upload-20260910-083535/fixture-failed-1440-light.png
docs/evidence/screenshots/studio-video-upload-20260910-083535/fixture-idle-1440-light.png
docs/evidence/screenshots/studio-video-upload-20260910-083535/fixture-processing-1440-dark.png
docs/evidence/screenshots/studio-video-upload-20260910-083535/fixture-processing-320-reduced.png
docs/evidence/screenshots/studio-video-upload-20260910-083535/fixture-processing-390-reduced.png
docs/evidence/screenshots/studio-video-upload-20260910-083535/fixture-processing-768-reduced.png
docs/evidence/screenshots/studio-video-upload-20260910-083535/fixture-ready-390-light.png
docs/evidence/screenshots/studio-video-upload-20260910-083535/live-1440-light.png
docs/evidence/screenshots/studio-video-upload-20260910-083535/live-390-light.png
docs/evidence/screenshots/studio-video-upload-20260910-083535/proof.json
```

The pack is 791,861 bytes. Its live captures show the capability held off; its
fixture captures are labelled UI-state evidence, not proof of a live upload.
Root's parallel Arcade browser acceptance may add a separate curated pack only
after its final files and claims are reviewed; it is outside this snapshot.

## Explicit exclusions — 1,116 untracked paths

- **1,115 historical/generated screenshot and JSON paths** under
  `docs/evidence/screenshots/**`, excluding only the ten-file Studio pack above.
- **1 root document:**
  `Authority_Closers_LMS_Learner_Journey_UX_Audit_FINAL.docx`.

Ignored caches and transient state, including `__pycache__`, `.tmp/**`, local
databases, logs, downloads, process markers and build caches, are also excluded
but are not part of the 1,279 non-ignored untracked count.

## Release composition boundary

This allowlist is coherent only as one reviewed exact commit because the UI,
global identity migration, versioned backup parity, Studio admission/processing
contracts and their tests cross package boundaries. It may be packaged with the
Studio video capability still fail-closed; it must not be described as an
operational upload/course-delivery release until scanner, durable storage,
runner, licensed long/4K input, publication and authorized learner playback
acceptance all pass.

Before staging, independently review all 77 advanced staging files, rehearse
`20260910_0028` against an isolated restore, approve the exact reserved-name
policy, validate the 251-path staged manifest against this document, run both
Application and Control-plane CI on the exact SHA, install the matching
parity-v8 foundation release, and deploy only the digest-bound application
artifact through the canonical staging controller. Production remains a
separate blocked gate.

## Refresh snapshot — Notifications, parity v9 and sealed full-film verifier

This append-only refresh preserves the 251-path snapshot above. It was captured
at `2026-09-10T16:24:20.3530343+05:30` from the same authoritative worktree,
branch and HEAD. No path was staged or committed, no database or service was
changed, no release was deployed and no credential value was inspected.

### Refreshed exact counts

| Measure | Count/result |
| --- | ---: |
| Files in staging commit `4e8d413b828ab750d7c5e20d1a9320d0f427c823` | 1,873 |
| Staging files present / absent in the working tree | 1,873 / 0 |
| Working files byte-identical to / advanced from staging | 1,787 / 86 |
| HEAD-to-staging delta paths | 66 |
| HEAD-to-staging paths preserved exactly / advanced further | 40 / 26 |
| HEAD-to-staging paths missing or reverted to HEAD | 0 |
| Modified tracked paths relative to HEAD | 96 |
| Untracked, non-ignored paths | 1,306 |
| Collapsed `git status --porcelain=v1` entries | 350 |
| All-path `git status --porcelain=v1 --untracked-files=all` entries | 1,402 |
| Refreshed candidate allowlist | 285 |
| Allowlisted / excluded untracked paths | 189 / 1,117 |
| `git diff --check` | PASS |

The exact refreshed manifest is the preserved 251 paths above plus the 34 paths
listed below, with no removal. All 285 paths exist. The disposition now is:

| Disposition | Count |
| --- | ---: |
| Exact staging carry-forward | 40 |
| Existing staging files advanced by this candidate | 86 |
| Truly new code, runtime assets, QA tooling and tests | 133 |
| Markdown evidence and intake | 16 |
| Curated screenshot/proof pack | 10 |

`packages/python/ac_platform/db/models.py` moved from exact carry-forward to
advanced because migration 0029 registers its model. Eight previously clean
staging files are now advanced and enter this manifest through the 34-path
addition:

~~~text
apps/learner-web/app/components/notifications-runtime.module.css
apps/learner-web/app/components/notifications-runtime.tsx
apps/learner-web/app/components/practice-availability.test.tsx
apps/learner-web/app/components/site-shell.tsx
apps/learner-web/app/lib/dev-api-proxy.test.ts
apps/learner-web/app/lib/dev-api-proxy.ts
apps/learner-web/app/lib/notifications.ts
tools/media-player-stress/README.md
~~~

### Exact 34-path addition

Notifications implementation, migration, tests and local acceptance tool —
23 paths:

~~~text
apps/learner-web/app/components/app-updates-inbox.test.tsx
apps/learner-web/app/components/app-updates-inbox.tsx
apps/learner-web/app/components/app-updates-provider.tsx
apps/learner-web/app/components/notification-target.ts
apps/learner-web/app/components/notifications-runtime.module.css
apps/learner-web/app/components/notifications-runtime.tsx
apps/learner-web/app/components/site-shell.tsx
apps/learner-web/app/lib/app-updates-api.test.ts
apps/learner-web/app/lib/app-updates-api.ts
apps/learner-web/app/lib/dev-api-proxy.test.ts
apps/learner-web/app/lib/dev-api-proxy.ts
apps/learner-web/app/lib/notifications.ts
db/migrations/versions/20260910_0029_app_update_read_receipts.py
packages/python/ac_platform/app_updates/__init__.py
packages/python/ac_platform/app_updates/application.py
packages/python/ac_platform/app_updates/catalogue.py
packages/python/ac_platform/app_updates/models.py
packages/python/ac_platform/http/app_updates.py
scripts/prove-local-app-updates.py
tests/integration/test_app_updates_postgresql.py
tests/unit/app_updates/__init__.py
tests/unit/app_updates/test_application.py
tests/unit/http/test_app_updates.py
~~~

Sealed full-film verifier source, package-owned byte manifest and tests — 6
paths:

~~~text
packages/python/ac_platform/media/data/full_film_bbb_4k_v1.json
packages/python/ac_platform/media/full_film_manifest.py
tests/unit/media/test_full_film_manifest.py
tests/unit/media/test_full_film_release_pack.py
tools/media-player-stress/prepare_full_film_release.py
tools/media-player-stress/README.md
~~~

Adjacent existing practice regression coverage — 1 path:

~~~text
apps/learner-web/app/components/practice-availability.test.tsx
~~~

Evidence and controlled intake — 4 paths:

~~~text
docs/evidence/20260910_APP_UPDATE_NOTIFICATIONS.md
docs/evidence/20260910_INTEGRATED_RELEASE_VALIDATION.md
docs/evidence/20260910_NATIVE_4K_OPEN_FILM_FIXTURE.md
docs/workflows/v0.1-alpha-experience/00-start-here/v0.2-alpha-coach-practice-update-intake-2026-09-10.md
~~~

The parity-v9 changes are advanced versions of four paths already present in
the original allowlist, so they are not duplicated in the 34-path addition:

~~~text
infra/application/scripts/restore-drill.py
infra/vps-foundation/scripts/ac-postgres-backup.py
infra/vps-foundation/scripts/ac-restic-postgres-restore-proof.py
tests/infra/test_capability_backup_parity.py
~~~

Each now explicitly maps head `20260910_0029` to
`ac-postgres-parity-v9` and adds
`app_update_read_receipts`. The focused evidence records 36 backend tests,
2 disposable PostgreSQL integration tests including the two-transaction
idempotency race, and 372 cross-catalogue parity tests passing. Independent
review reports no remaining Critical or Important backend finding.

The package-owned full-film manifest and loader are release inputs. The 1.46 GB
generated film pack, source downloads, probes and `.artifacts/**` outputs are
ignored local evidence, not Git or application-artifact inputs. The verifier
does not create database, READY, binding, publication or playback authority.

### Refreshed exclusions

Exactly 1,117 non-ignored untracked paths remain excluded:

- 1,116 screenshot/JSON outputs below `docs/evidence/screenshots/**`, from
  1,126 total paths there after retaining only the original ten-file Studio
  pack. This includes
  `docs/evidence/screenshots/app-updates-local-20260910/drive-register.json`;
  the durable Drive readback is documented in the allowlisted Notifications
  evidence, while this generated local registration output is not a release
  input.
- `Authority_Closers_LMS_Learner_Journey_UX_Audit_FINAL.docx`.

Ignored `.tmp/**`, `.artifacts/**`, caches, local databases, logs,
downloads, process markers and Next build/dev state remain outside both the
1,306 non-ignored untracked count and the release.

### Smallest coherent releasable boundary

The honest boundary is one reviewed 285-path commit: the original 251-path
candidate plus the exact 34-path addition above. Notifications needs its UI,
strict learner proxy behavior, authenticated API, model, migration 0029,
parity-v9 catalogues and tests together. The full-film boundary contains only
the verifier code and sealed package manifest; it does not include the
generated film bytes or activate publication. No WordPress path is changed.

The local Notifications acceptance is complete: three-app ESLint and
typechecking passed, 105 frontend files / 2,083 tests passed, and normal-login
browser proof covered eight light/dark viewport states, server-backed read
persistence and private/no-store GET/POST responses. Drive filing was read back
and is labelled local, not deployed. These are checkpoints, not an exact
immutable release result.

### Concrete blockers at this snapshot

1. **The candidate is not frozen.** HEAD is still
   `7bdd069d4bf00561edcab90b1679666205708185`; 96 tracked paths are modified
   and 1,306 paths are untracked. Coach media-preview wiring was still in
   progress. Any new path after this timestamp requires another explicit
   allowlist append; content-only changes still require the final gates below.
2. **No exact-candidate CI or package exists.** The final 285-path state has not
   been staged, committed, reviewed in a clean clone, container-built or
   emitted as the one exact-SHA digest-bound application artifact.
3. **Full frozen-tree validation remains.** The Notifications-specific and
   full-film-specific checks passed, but the earlier Python checkpoint
   deliberately excluded changing media code. Run the complete Ruff, mypy,
   Python unit/integration/migration/schema-drift and standalone
   operations-web suites on the frozen tree. Re-run the three-app Node gates
   after the final Coach changes. Do not run `next build` in the live app
   directories; the isolated BuildKit/Application CI path owns builds.
4. **Migration rehearsal and policy closure remain.** Rehearse migrations 0028
   and 0029 on an isolated, current staging-data restore. General global Cohorva
   username behavior is approved, but the exact reserved-name set and collision
   rehearsal remain separate gates. Do not repair collisions with direct SQL.
5. **The installed foundation is not evidenced at parity v9.** The last durable
   evidence names `foundation-74631e0dd94a1d54a2e2b88bc925e47e0e0c7029`
   with parity v7. Before migration 0029 is promoted, install and validate the
   checksum-bound foundation archive from the same final commit so the managed
   backup and restore helpers recognize parity v9.
6. **Staging acceptance remains.** After deployment, run the authenticated
   Notifications read/unread persistence proof against staging, the bounded
   Coach media-preview acceptance owned by its implementer, and a canonical
   off-site backup/restore proof at exact migration head 0029. Local film
   verification is not deployed playback evidence.

Production is not part of this sequence. Its previously recorded managed
configuration presence probe remains 0/13; no staging value may be copied to
close it.

### Exact safe release sequence

No command below was run by this inventory. At an authorized freeze:

1. Recompute this same inventory after Coach work stops, inspect
   `git diff --check`, and create a reviewed 285-line pathspec from the
   preserved 251 paths plus the exact 34 above. Stage only that pathspec:

   ~~~powershell
   git add --pathspec-from-file=<reviewed-285-path-allowlist.txt>
   git diff --cached --name-only
   git diff --cached --check
   git diff --cached --stat
   ~~~

   Require exactly 285 staged names and an empty set difference in both
   directions. Never use `git add -A`; the 1,117 excluded paths must remain
   unstaged.
2. Review the complete staged diff, commit normally, and record the full
   40-character SHA. Require no tracked/index residue with:

   ~~~powershell
   git diff --exit-code
   git diff --cached --exit-code
   git rev-parse HEAD
   ~~~

   The known excluded untracked files may remain in this dirty worktree; release
   verification and packaging must use the immutable commit/clean CI checkout.
3. Run the full local gates above where safe, then push the frozen branch/PR.
   Require both Application and Control-plane workflows to pass on the exact
   commit. Because Control-plane has no manual-dispatch trigger, its required
   result must come from that exact PR/push.
4. While the reviewed branch still points exactly at the frozen commit,
   dispatch `.github/workflows/application.yml`. Its manual packaging job
   runs `pnpm validate`, migration tests and isolated container builds, and
   publishes `ac-application-<full-SHA>`. Verify the completed run's
   `headSha` equals the frozen SHA and that exactly one unexpired artifact
   exists; the deploy controller independently enforces these conditions and
   its digest.
5. Rehearse 0028/0029 on the isolated staging restore. From the same full SHA,
   build and checksum the canonical Git archive and use the reviewed
   `infra/vps-foundation/bootstrap-host.sh runtime` installation path to
   install parity v9. Validate installed managed-file hashes, services/timers
   and public foundation health. Do not copy individual helpers or treat VPS
   edits as authoritative.
6. Preflight staging configuration by presence through the managed release
   path without printing values. With explicit deployment authority, run only:

   ~~~powershell
   pwsh -NoProfile -File .\scripts\Deploy-Staging.ps1 -ReleaseSha <full-reviewed-commit> -TargetEnvironment staging
   ~~~

   The controller must retrieve the exact-SHA artifact, verify its digest,
   archive the exact application source, take and inspect the pre-migration
   backup, apply migrations through the canonical runner, switch services and
   complete its staging/WordPress-preservation smoke checks.
7. Record the controller receipt and migration head, then run the bounded
   authenticated staging browser checks and canonical parity-v9 backup/off-site
   restore proof. Preserve failures append-only. Only those results can close
   staging readiness for this immutable commit.

Any later production promotion is a separate approval and configuration gate,
using the same reviewed immutable artifact rather than rebuilding or manually
patching it.

### Post-snapshot concurrent Coach paths

Immediately after the timestamp above, the parallel Coach media-preview slice
created or changed these seven paths:

~~~text
apps/admin-web/app/components/studio/studio-video-preview.test.tsx
apps/coach-web/app/v1/[...path]/route.ts
packages/python/ac_platform/media/studio_video_preview.py
packages/typescript/operations-web/src/local-studio-preview-transport.ts
packages/typescript/operations-web/src/studio/studio-video-preview-api.ts
packages/typescript/operations-web/src/studio/studio-video-preview.module.css
packages/typescript/operations-web/src/studio/studio-video-preview.tsx
~~~

They are deliberately not counted in the 285-path timestamped manifest because
that owned slice was still in progress. They are neither rejected nor
implicitly allowlisted. Once stable, the final freeze must review them, append
their exact disposition, and recompute every total before staging.

## Provisional supplement — Coach private video preview

This append-only supplement was captured at
`2026-09-10T18:42:08.7835185+05:30`. It preserves the earlier 251- and
285-path snapshots and their hashes/counts unchanged. The preview owner was
still completing real-browser acceptance, so this section is **mutable and not
a freeze manifest**. No file was staged, committed or deployed, and no service,
database, credential or remote state was changed.

### Provisional counts

| Measure | Count/result |
| --- | ---: |
| Files in staging commit `4e8d413b828ab750d7c5e20d1a9320d0f427c823` | 1,873 |
| Staging files present / absent in the working tree | 1,873 / 0 |
| Working files byte-identical to / advanced from staging | 1,786 / 87 |
| Modified tracked paths relative to HEAD | 97 |
| Untracked, non-ignored paths | 1,320 |
| Collapsed / all-path porcelain entries | 365 / 1,417 |
| Preserved frozen snapshot | 285 paths |
| Provisional preview addition | 14 paths |
| Provisional candidate if all additions pass review | 299 paths |
| Provisionally allowlisted / excluded untracked paths | 202 / 1,118 |
| `git diff --check` for tracked changes | PASS |

The 14-path addition consists of one staging file advanced by the preview
proxy and thirteen new, non-ignored files. Its provisional disposition changes
the 285-path totals to 40 exact staging carry-forwards, 87 advanced staging
files, 145 truly new code/assets/tests/tools, 17 Markdown evidence/intake files
and the same ten curated screenshots: 299 total.

### Exact provisional 14-path addition

Runtime code and styling — 8 paths:

~~~text
apps/coach-web/app/v1/[...path]/route.ts
packages/python/ac_platform/http/studio_video_preview.py
packages/python/ac_platform/media/studio_video_preview.py
packages/typescript/operations-web/src/local-studio-preview-transport.ts
packages/typescript/operations-web/src/studio/studio-lesson-video-preview.tsx
packages/typescript/operations-web/src/studio/studio-video-preview-api.ts
packages/typescript/operations-web/src/studio/studio-video-preview.module.css
packages/typescript/operations-web/src/studio/studio-video-preview.tsx
~~~

Focused tests and local acceptance tool — 5 paths:

~~~text
apps/admin-web/app/components/studio/studio-video-preview.test.tsx
apps/admin-web/app/lib/studio-video-preview-proxy.test.ts
scripts/prove-local-studio-video-preview.py
tests/unit/http/test_studio_video_preview.py
tests/unit/media/test_studio_video_preview.py
~~~

Append-only implementation evidence — 1 path:

~~~text
docs/evidence/20260910_STUDIO_VIDEO_PREVIEW.md
~~~

The preview also advances these six paths that were already present in the
285-path manifest; they must be reviewed at their final bytes but do not
increase the path count:

~~~text
apps/admin-web/app/lib/dev-api-proxy.test.ts
packages/python/ac_platform/http/studio_media.py
packages/typescript/operations-web/src/dev-api-proxy.ts
packages/typescript/operations-web/src/studio/studio-course-editor.tsx
packages/typescript/operations-web/src/studio/studio-video-panel.tsx
packages/typescript/operations-web/src/studio/studio-video-upload.tsx
~~~

The exact addition contains only `.py`, `.ts`, `.tsx`, `.css` and `.md`
sources. It contains no secret/environment file, browser profile, cookie or
authentication state, local database, log, cache, process marker, source or
generated video, screenshot, build output, `.tmp/**` or `.artifacts/**` path.
The unrelated untracked
`docs/evidence/20260910_LOCAL_RESTART_FOLLOWUP.md` is not implicitly included;
it remains in the provisional excluded count pending separate scope review.

### Preview evidence boundary still pending

`scripts/prove-local-studio-video-preview.py` is a reviewable test input. Its
eventual run directory, private media bytes, screenshots and `proof.json` below
`.tmp/local-platform/**` remain ignored local evidence and must not be staged.
After the owner completes the run, append only the sanitized command/result,
exact ignored proof path and bounded claims to
`docs/evidence/20260910_STUDIO_VIDEO_PREVIEW.md`. Any deliberately retained
screenshot would require a new explicit curated allowlist append; none is
included here.

The final proof must establish the authenticated same-session descriptor and
byte path, bounded HEAD/range behavior, retry/focus recovery, cancellation and
late-session failure handling, current-version drift rejection, private
`no-store` responses and absence of unexpected browser errors. Local proof is
not staging proof and does not create publication or learner-playback authority.

### Exact-SHA release prerequisite found during this refresh

The current preview runtime is intentionally local/test-only, not merely
disabled by a missing staging setting. `StudioVideoRuntime.validate()` and
`compose_local_studio_video_runtime()` reject environments outside `local` and
`test`. The normal staging application creates the default media runtime, so
`studio_video_runtime` is absent and the installed preview route returns the
typed fail-closed `503 studio_video_preview_not_configured` after authentication.

Therefore this provisional candidate may be frozen and released with the Coach
preview UI visibly unavailable, but it cannot claim an operational staging
upload-preview flow. Operational staging preview requires a separate reviewed
staging-safe storage/runtime composition and its scanner/storage acceptance; no
environment-value change or manual VPS file copy can close that boundary.

For the fail-closed release boundary, no further packaging configuration was
found beyond final source stabilization and the existing gates. The actionable
freeze checklist is:

1. Stop all preview writers, record the completed ignored browser proof in the
   evidence document, and recompute the path/content inventory. Confirm whether
   the intended staging claim is explicitly fail-closed; otherwise do not
   freeze this release.
2. Build a reviewed 299-line pathspec only if the exact 14 additions above are
   accepted and no further path appears. Require bidirectional equality with
   the staged names, `git diff --cached --check`, and a complete staged-diff
   review; never use `git add -A`.
3. Run the complete frozen-tree Python, migration/schema, operations-web and
   three-app Node gates. Use Application CI/BuildKit for isolated production
   builds rather than either live app's `.next` directory.
4. Push the immutable full SHA and require both Application and Control-plane
   checks on that exact commit. Dispatch Application packaging only while the
   reviewed branch still resolves to that SHA; require one unexpired,
   digest-bound `ac-application-<full-SHA>` artifact with matching `headSha`.
5. Rehearse migrations 0028/0029 on the isolated staging restore, then install
   and validate the checksum-bound foundation archive from the same commit so
   managed backup/restore helpers recognize parity v9. The currently installed
   foundation remains parity v7 and cannot safely protect head 0029.
6. Only after those gates and explicit deployment authority, invoke
   `scripts/Deploy-Staging.ps1` for `-TargetEnvironment staging`; retain its
   receipt and follow with authenticated staging acceptance and the canonical
   parity-v9 off-site restore proof. Production remains a separate configuration
   and approval gate.

### Deployable Studio composition handoff

The repository already supplies useful pieces, but not a deployment
composition. The reusable contracts are:

- environment-separated durable roots from
  `infra/application/environments/{staging,production}.env` and the application
  installer's validated `AC_STATE_ROOT`;
- release-owned capability-policy, preflight and Compose-override selection on
  both upgrade and rollback, as demonstrated by `staging-public-films.py`,
  `public-films.py` and their two read-only API bind mounts;
- tenant-namespaced, immutable, checksummed and quota-bounded objects in
  `VideoFileStorage`;
- the exact-kind-only `StudioVideoJobWorker` and bounded `StudioVideoRunner`;
- the checksum-verified private scanner manager in `infra/media-safety`; and
- encrypted Restic coverage of `/srv/authority-closers`, plus the separate
  parity-versioned logical PostgreSQL backup.

None of those pieces alone authorizes or safely launches mutable Studio media
on the VPS. The minimum implementation owned by the release integrator is:

1. Add an immutable, environment-scoped Studio capability policy and preflight
   following the public-film selector pattern. It must derive fixed storage and
   scratch paths from the selected environment, pin byte/object/temp/rendition
   bounds and a controlled retention-policy identity, reject ambient enable
   flags and validate the candidate and rollback release before writers stop.
   Expected deployment files are a new capability JSON, selector/preflight
   script and Compose override, plus focused infra tests.
2. Add explicit settings and a sealed deployed composition in
   `packages/python/ac_platform/application/settings.py`,
   `packages/python/ac_platform/media/runtime.py` and
   `packages/python/ac_platform/media/studio_video_runtime.py`. The normal
   `create_default_media_runtime()` path—not dependency injection—must compose
   it only when the release policy and exact environment agree. Keep the
   general provider disabled, retain the same database session factory and
   preserve all tenant/program/owner/current-version checks.
3. Mount one pre-created, non-symlink, mode/owner-checked
   `video-objects` directory read-write into both API and a dedicated Studio
   worker. Keep it isolated per environment. Mount a separate bounded scratch
   directory into the Studio worker and set its temporary-directory location;
   the common 64 MiB `/tmp` tmpfs cannot hold the configured FFmpeg source and
   output envelope. Scratch is non-authoritative and needs explicit crash
   reconciliation rather than being treated as durable media.
4. Add a dedicated Studio worker launcher/service using the existing exact job
   kind. Do not broaden `ac_platform.worker` or run an ad-hoc host process.
   Include the new service in installer maintenance fencing, startup,
   health/readiness, rollback/forward-recovery handling, container identity
   assertions and the final deployment receipt.
5. Put pinned, verified `ffmpeg` and `ffprobe` binaries in the immutable worker
   runtime image and prove their identity/startup in Application packaging.
   The current Python image installs neither; host binaries are not a valid
   container dependency. Reusing the API image is possible only if its expanded
   binary surface and hashes are deliberately accepted and tested.
6. Connect API/Studio worker to the scanner over an exact private Docker
   network and fixed service identity. The current scanner is a separately
   managed **local pilot**, exposes only host loopback and is currently
   unhealthy; it cannot be relabelled as staging/production readiness. Promote
   its immutable manager/policy, preserve bounded INSTREAM behavior and fresh
   definition proof, and keep upload capability unavailable when scanner
   readiness is stale or unhealthy without taking unrelated application
   capabilities down.
7. Update `infra/application/compose.yaml`,
   `infra/application/scripts/install-application-release.sh`, the relevant
   environment profiles and `scripts/Deploy-Staging.ps1` so the selected
   capability is release-owned, the API and worker share only the intended
   storage, and release smoke verifies the additional service. Extend
   `tests/infra/test_application_release.py` and add a focused deployment-policy
   suite covering off-by-default, environment separation, rollback selection,
   paths/modes, mounts, limits, scanner network, binary pinning, service fencing
   and receipts.
8. Add a coordinated bytes-plus-database recovery contract. Although Restic
   scans the state root, its daily filesystem snapshot and the five-minute
   logical database snapshot are not a consistency pair. A restored newer DB
   could reference video bytes absent from an older filesystem snapshot. The
   release must define a writer fence/order, immutable object inventory and
   matching restore proof, then include worst-case media churn in the existing
   8 GiB R2 guard. Do not exclude private bytes without another proven durable
   copy, and do not assume Restic deduplication makes the capacity safe.
9. Close the filesystem durability note already documented by
   `VideoFileStorage`: directory-entry synchronization and target-filesystem
   crash/recovery evidence are prerequisites for VPS activation. File-only
   `fsync` and process-restart tests do not establish host/power-loss durability.

Direct R2 application-object storage is not the smaller shortcut. The existing
`S3CompatiblePrivateObjectStorage` deliberately refuses construction because a
peer/IP-bound transport and immutable activation verifier are absent. Enabling
it would additionally require separate bucket-scoped application credentials,
an updated cost/operation model, `AC-GOV-AUD-001` and `GAP-MEDIA-001` approval
references and provider activation evidence.

The VPS-local path avoids a new object-storage provider, but controlled storage
and retention authorization is still missing. The default lifecycle hook
deletes nothing and no approved retention window is encoded. Before real
production uploads, the controlled owner must approve the private-media store,
retention/deletion policy, backup retention and recovery behavior; these
semantics must not be inferred from the public-film fixture or from current
Restic retention. A staging-only licensed technical fixture can be activated
only under its own exact, non-production policy and successful scanner,
filesystem, worker, backup and browser gates.

### Post-capture proof-test addition

At `2026-09-10T18:53:24.1588451+05:30`, while this section was explicitly
mutable, the preview owner added one focused offline proof-contract test:

~~~text
tests/unit/test_studio_video_preview_proof.py
~~~

It exercises sanitized request denials, external/write fail-closed behavior,
exact private preview response paths/headers and locator-scoped video wait
predicates. Its `token=secret` strings are synthetic redaction fixtures, not a
credential or captured authentication value. The file is ordinary Python
source and contains no browser state or generated proof output.

This makes the latest provisional supplement **15 paths** and the provisional
candidate **300 paths**: 40 exact staging carry-forwards, 87 advanced staging
files, 146 truly new code/assets/tests/tools, 17 Markdown evidence/intake files
and ten curated screenshots. Current counts at that instant were 97 modified
tracked paths, 1,321 non-ignored untracked paths, 366 collapsed porcelain
entries and 1,418 all-path entries. Provisionally allowlisted/excluded
untracked paths were 203/1,118. This is still not the final freeze snapshot.
