# Studio video preview: local implementation evidence

Status: implemented for the isolated local/test runtime. This is not evidence of a staging or production upload/preview release. Actual browser verification is recorded separately below when completed.

## Backend

Implemented the local/test-only Studio preview seam in:

- `packages/python/ac_platform/media/studio_video_preview.py`
- `packages/python/ac_platform/http/studio_video_preview.py`
- `packages/python/ac_platform/http/studio_media.py`
- `packages/python/ac_platform/http/app.py`
- `packages/python/ac_platform/http/surfaces.py`

The descriptor route is:

`GET /v1/admin/studio/programs/{program_id}/videos/{asset_id}/versions/{version_id}/preview`

It returns only the strict `{program_id, asset_id, version_id, content_type, byte_length, duration_seconds, preview_href}` contract. `preview_href` is the exact same-origin `/preview/bytes` path. The byte route supports `GET`, `HEAD`, one bounded single byte range, `206`/`416`, `ETag`, and `private, no-store` headers.

Each request performs fresh session resolution plus `catalog_write` and `catalog_read` authorization, then exact tenant/course/owner or approved-course predicates. The relational snapshot requires a current ready video, immutable `StudioVideoUpload` provenance, a ready completion intent whose source identity matches the version, and the canonical progressive key shape `{version.object_key}/attempts/{uuid}/renditions/progressive.mp4`. Storage verification runs off the event loop after the short authorization transaction closes. A second fresh relational snapshot is required before returning metadata or a body. The preview uses the configured `VideoFileStorage` progressive output only; it does not issue learner grants, mutate learning state, publish bindings, or expose object URLs.

Storage inspection and response streaming are capped by one in-flight preview slot. Blocking work is owned and drained across native task cancellation. Streamed bytes are length/checksum checked and revalidated against the exact object metadata before completion; changed or replaced objects fail closed.

When no exact local/test `StudioVideoRuntime` is composed, the routes remain inert and return typed `503 studio_video_preview_not_configured` only after authentication. No runtime restart, upload, database mutation, provider activation, or deployment was performed for this evidence.

## Verification

- `.venv\Scripts\ruff.exe check packages/python/ac_platform`: passed.
- `.venv\Scripts\mypy.exe packages/python/ac_platform`: passed (`192 source files`).
- Focused preview tests: `15 passed`.
- Existing Studio composition/library/byte/processing/runtime suites: composition `10 passed`, library `28 passed`, byte transport `41 passed`; the broader combined run was green through its final test progress output.
- PostgreSQL playback integration was attempted with the repository `.venv`; it was skipped because no PostgreSQL URL was configured (`media delivery renewal PostgreSQL URL is not configured`).

## Coach interface and local byte transport

The shared Studio interface now offers an explicit **Preview video** action for a ready upload, a selected ready library item, and an approved saved lesson binding. It does not fetch media until selected, autoplay, publish the course, create learner grants, or write learner progress. Identity/session changes discard the old preview. The saved-lesson wrapper rechecks the returned version status before exposing its binding.

The player has native controls, inline mobile playback, metadata-only preload, bounded access/load timeouts, actionable retry, and close/unload behavior. Focus is retained on retry and on media failure, then returned to the trigger on close. Styling uses the existing Studio theme tokens and reduced-motion handling.

The local Coach proxy allows only exact authenticated descriptor/byte paths. Byte responses stream with backpressure and bounded lifetime instead of being buffered through the existing 8 MiB JSON transport. Only an allowed single range and the existing session cookie are forwarded. Redirects, external object URLs, caller-selected origins, unexpected bodies, and credential/header overrides are rejected. The staging proxy allowlist has **not** been widened to pretend the local transport is deployed.

## Independent review and frontend verification

- Independent backend re-review: clear of Critical/Important findings after fixes for transaction lifetime, canonical rendition paths, fresh post-storage authorization, bounded hashing, cancellation drain, and stream object-identity verification. The reviewer ran **120 related tests**, Ruff, and strict mypy successfully.
- Independent UI/proxy re-review: clear of Critical/Important findings after keyboard-focus and returned-version-status fixes. **52 focused tests passed**.
- Full Admin suite: **27 files, 631 tests passed**. Full Coach suite: **1 file, 14 tests passed**.
- The concurrent three-app run had one Learner subprocess startup timeout (`spawnSync ETIMEDOUT`, five-second bound). The unmodified standalone rerun then passed **79 files, 1,490 tests**. Together with Admin and Coach, the completed per-app runs cover **107 files, 2,135 tests**; the initial timeout remains recorded rather than erased or hidden by relaxing the test.
- Admin/Coach ESLint and TypeScript checks passed. The seven changed shared preview/transport/panel/upload files were additionally checked directly with the Admin ESLint config from the repository root, with no lint findings (Next emitted its root-level pages-directory configuration notice).
- The browser proof pins the licensed 12-second source by size and SHA-256; it must verify normal Coach sign-in, actual upload/processing, decoded playback, seeking, private response headers, mobile/desktop layout, and unloading. A short fixture does not establish full-length 4K, 1–2 GiB uploads, captions, or deployed behavior.

## Deployment limits and scanner follow-up

- The default staging/production runtime still does not compose `StudioVideoRuntime`; it rejects non-local injection. A separately reviewed VPS storage/worker/runtime composition is required before operational upload/preview can be claimed there. A feature flag alone does not supply this.
- The live scanner's explicit IPv4 PING/version and canonical clean/EICAR checks passed on 2026-09-10, but Docker still reports unhealthy: its image healthcheck resolves `localhost` to IPv6 while clamd binds IPv4. A canonical immutable healthcheck/proof/upgrade repair is in progress; no manual container repair was performed.
- The currently attested scanner source limit remains **100 MiB**. The 14,538,778-byte proof fixture fits; the separate 605,687,519-byte full-length film does not. This slice does not increase that limit or establish large-upload support.
