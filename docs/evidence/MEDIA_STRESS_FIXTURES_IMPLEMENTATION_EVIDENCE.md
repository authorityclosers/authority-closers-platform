# Media stress fixture implementation evidence

Status: implementation evidence only. This is a non-production test-fixture
pipeline; it is not Authority Closers course content, a provider activation,
an approval to serve media, or a production release decision.

## Controlled boundaries used

The implementation follows the repository's controlled-source order and the
media/security/release interpretations recorded in:

- [Controlled source register](../traceability/CONTROLLED_SOURCE_REGISTER.md)
  (Master Index, BRD, PRD, SRS, Data/Tenancy, API/MCP, Security/IAM/privacy,
  Telemetry, DevOps/SRE, QA/release, and ADR/risk).
- [Media vertical-slice implementation evidence](MEDIA_VERTICAL_SLICE_IMPLEMENTATION_EVIDENCE.md),
  which keeps provider callbacks, external storage, signed delivery, CDN/live
  playback, and production deployment unavailable.
- [Environment contract](../contracts/ENVIRONMENT_CONTRACT.md), which keeps
  external activation separately gated and distinguishes local/test seams from
  staging/production composition.
- [Authorization matrix](../security/AUTHORIZATION_MATRIX.md), which requires
  deny tests for every allow path and server-side authority for playback.

The stress seam is deliberately subordinate to those controls. It returns a
verified local descriptor only when the caller supplies an explicit test,
development, or staging environment, an opt-in flag, an already-verified
provider activation, a server-created opaque authorization context, and a
server-created playback grant bound to that context. Both external verifiers
receive those tenant/person/session/activity-scoped objects; the seam does not
interpret their business meaning or issue either gate. It does not write
canonical learning state, create progress/evidence, or turn a public URL into a
playable source. Production settings and composition reject the opt-in.

## Open-source fixture provenance

The external fixtures are official Blender Foundation Big Buck Bunny archives
and the official Blender Studio Caminandes 2 archive. The [Blender
film/about page](https://peach.blender.org/about/) identifies the Peach open
movie as Creative Commons Attribution 3.0, and the [Caminandes 2 film
page](https://studio.blender.org/projects/api/assets/2363/) identifies that
film as Creative Commons Attribution 4.0. The checked-in manifest records each
official download index, exact archive URL, source-page URL, source index, the
source index date with an explicit basis (not an HTTP `Last-Modified`
assertion), retrieval date, attribution, and both archive/extracted SHA-256
values. The recorded license URLs are the [Creative Commons Attribution 3.0
deed](https://creativecommons.org/licenses/by/3.0/) and [Creative Commons
Attribution 4.0 deed](https://creativecommons.org/licenses/by/4.0/).

| Fixture            | Exact source archive                                                                                                                | License / attribution                                           | Archive SHA-256                                                    | Extracted video SHA-256                                            |
| ------------------ | ----------------------------------------------------------------------------------------------------------------------------------- | --------------------------------------------------------------- | ------------------------------------------------------------------ | ------------------------------------------------------------------ |
| `bbb-4k-30-normal` | [`bbb_sunflower_2160p_30fps_normal.mp4.zip`](https://download.blender.org/demo/movies/BBB/bbb_sunflower_2160p_30fps_normal.mp4.zip) | CC BY 3.0; Blender Foundation 2008, Janus Bager Kristensen 2013 | `750b255c6d9fee1e2a03a6716d4f358bca56e9115bf3e06a66162fc5272ae151` | `37f0ff251a606c2dcfa26c19fe6bf843234b4e7a8889cfab50bc26f644e55520` |
| `bbb-320x180-24`   | [`BigBuckBunny_320x180.mp4.zip`](https://download.blender.org/peach/bigbuckbunny_movies/BigBuckBunny_320x180.mp4.zip)               | CC BY 3.0; Blender Foundation / Big Buck Bunny                  | `109e3ede8790bd633f374ca311d9cc61dce8d7f98f5b0797ca98199c9fbceedf` | `f78f39603e6774907f2faafabf26a667f4a6fc31769ec304a8a8f7c62d280508` |
| `caminandes-gran-dillama-1080p` | [`caminandes_gran_dillama.mp4.zip`](https://download.blender.org/demo/movies/caminandes_gran_dillama.mp4.zip) | CC BY 4.0; Blender Foundation / Blender Studio; directed by Pablo Vazquez | `2e54abfb18dcb0a25d41e7b5d97fd51b226cec58d2fbcad101cf6deecea8c48b` | `468e6743c674689a728726bbe4bb4b2a65bd8702a89f021af26a8bb4d450eebd` |

The 4K fixture is 3840×2160 at 30 fps; the low-resolution Big Buck Bunny
fixture is 320×180 at 24 fps; and the Caminandes fixture is 1920×1080 at 24
fps. All remain test inputs only and must never be labeled as course media.
The manifest's download allowlist contains only the three exact
`download.blender.org` archive paths; arbitrary public URLs, HTTP, non-443
ports, redirects outside the exact path, URL credentials, query strings, and
fragments are rejected.

Three additional fixtures are generated locally by the bounded FFmpeg
`testsrc2` lavfi source. Their dimensions/durations and SHA-256 values are
also pinned in [`fixture-manifest.json`](../../tools/media-player-stress/fixture-manifest.json);
they contain no third-party or course content.

## Reproducible harness

- [`fixture-manifest.json`](../../tools/media-player-stress/fixture-manifest.json)
  is the single source allowlist and metadata/checksum registry. It declares
  six rendition profiles (2160p through 360p), 4-second target segments,
  explicit test-only content boundaries, and a checksum-pinned FFmpeg 8.1.1
  generator prefix for synthetic fixtures. The fixture, caption, network, and
  test manifests each have an immutable hardcoded SHA-256 pin; a changed
  checked-in authority requires an intentional code change to update its pin.
- [`fixture_harness.py`](../../tools/media-player-stress/fixture_harness.py)
  validates the registry, downloads only an exact allowlisted HTTPS archive,
  verifies the archive digest before extraction, extracts one exact regular
  archive member, runs bounded FFmpeg lavfi generation, and verifies ffprobe
  metadata before returning evidence.
- [`stress_fixtures.py`](../../packages/python/ac_platform/media/stress_fixtures.py)
  rechecks the exact immutable registry digest, exact cache/archive paths,
  media container metadata, license/provenance record, generated-source
  arguments, and cached bytes before a private descriptor can be returned. The
  generated FFmpeg argv is an exact allowlist containing only the approved
  lavfi test source and bounded output options; no local or network input path
  can be introduced. Descriptor construction is sealed and still requires
  typed provider/playback verifiers plus matching server-created opaque
  authorization/grant scope; no caller-supplied media metadata can create an
  approval or authority fact.
- [`acquire_media_fixtures.py`](../../tools/media-player-stress/acquire_media_fixtures.py)
  exposes manifest, acquire, generate, and verify commands. All bytes stay
  under the ignored `tools/media-player-stress/.artifacts/` boundary; no
  binaries are tracked. The CLI accepts only the exact checked-in manifest
  path and rejects `..`, symlink, and Windows reparse-point escapes.
- [`build_hls_ladder.py`](../../tools/media-player-stress/build_hls_ladder.py)
  renders a bounded local HLS VOD ladder with relative playlists, MPEG-TS
  segments, independent-segment markers, and per-output checksums. It rejects
  discontinuities, requires an exact VOD timeline and target-duration bound,
  and probes every segment's MPEG-TS PTS/DTS metadata for finite contiguous
  boundaries that match `EXTINF`, requested duration, and every rendition.
  It derives
  each rendition's `CODECS` from ffprobe MIME codec metadata, requires every
  segment in that rendition to agree, requires the encoded container/content
  type to be MPEG-TS/video/mp2t, validates the master playlist against those
  exact values and six approved resolutions, and records the FFmpeg
  version/redacted arguments in `hls-manifest.json`. The output also includes
  a test-only local byte-range slice harness and aligned segment-timeline
  quality-switching evidence; it never performs an HTTP/provider request.
- [`captions-manifest.json`](../../tools/media-player-stress/captions-manifest.json)
  and [`stress-en.vtt`](../../tools/media-player-stress/captions/stress-en.vtt)
  are synthetic WebVTT checkpoints, not course transcripts; the captions
  authority is also digest-pinned before it is consumed.
- [`network-scenarios.json`](../../tools/media-player-stress/network-scenarios.json)
  and [`test-manifest.json`](../../tools/media-player-stress/test-manifest.json)
  define deterministic metadata for LAN, fast/slow cellular, timeout,
  midstream loss, offline, range denial, grant expiry, and provider-unavailable
  states. Runtime schema checks constrain range-request and expected-state
  values, and cross-check all IDs. They do not call a live endpoint or stand in
  for canonical state.

The CLI does not use Playwright. The existing browser fake-API harness is a
separate development diagnostic and was not used as evidence for acquisition,
HLS generation, provider access, or production readiness.

## Checks performed in this worktree

### Current-registry revalidation (2026-09-10)

- `uv run python tools/media-player-stress/acquire_media_fixtures.py manifest`
  validated the exact checked-in registry and emitted manifest SHA-256
  `fc61c87d5428d53d35b82061a53fbdbd9967b8bf658c6d0425a78a07bc106290` with
  fixture IDs `bbb-4k-30-normal`, `bbb-320x180-24`,
  `caminandes-gran-dillama-1080p`, `generated-16x9-4s`,
  `generated-4x3-6s`, and `generated-wide-3s`, plus six rendition profile IDs.
- `uv run pytest -q tests/unit/media/test_stress_fixture_manifests.py
  tests/unit/media/test_stress_fixture_composition.py` passes the focused
  registry/composition suite: `25 passed`. The suite includes the wall-clock
  download deadline, production/local denial, typed provider/grant verifiers,
  exact cache/path and checksum/provenance checks, caption/FFmpeg allowlists,
  redirect handling, and network-manifest checks.
- `uv run pytest -q tests/infra/test_public_films.py
  tests/infra/test_staging_public_films.py` passes the public-film packaging
  and staging-boundary checks: `87 passed, 7 skipped` on Windows. The skipped
  cases require POSIX atomic-install semantics unavailable on this host.
- `uv run pytest -q tests/integration/test_public_film_http_postgresql.py`
  collected the two real ASGI/PostgreSQL playback checks but skipped both
  because the guarded staging PostgreSQL URL is not configured locally. Once
  that isolated target and the actual pack are supplied, the second check also
  proves `/v1/auth/logout` clears the cookie and denies a previously issued
  playback URL; the skip is not staging acceptance.
- The staging capability remains source-disabled in
  [`staging-public-films.json`](../../infra/application/capabilities/staging-public-films.json):
  no policy-on release was selected, no current VPS state was changed, and no
  external media was downloaded during this revalidation. The implementation
  is staging-prepared but not staging-activated; activation still requires an
  explicit reviewed policy-on release, Linux install/preflight evidence, and
  import/playback QA.

The following fixture acquisition, fresh-cache generation, and six-profile HLS
render checks are historical evidence from the earlier implementation passes;
they are retained below with their original scope. They are not a claim of
current staging activation.

- `uv run python tools/media-player-stress/acquire_media_fixtures.py manifest`
  (historical 2026-09-07 run) validated the pre-Caminandes registry and emitted
  the then-current five fixture IDs and six rendition profile IDs.
- `uv run python tools/media-player-stress/acquire_media_fixtures.py verify`
  (historical 2026-09-07 run) verified both downloaded Blender
  archives/extractions and all three generated MP4s with ffprobe dimensions,
  frame rates, durations, codecs, and MP4 container metadata; all five
  pre-Caminandes fixture records passed their pinned archive/extracted SHA-256
  checks.
- Fresh-cache generation was also exercised with the three `generate` commands
  under `tools/media-player-stress/.artifacts/fresh-generation`; all emitted
  hashes matched the pinned manifest and the FFmpeg 8.1.1 generator prefix,
  followed by a verify run naming all three generated fixture IDs.
- `uv run python tools/media-player-stress/build_hls_ladder.py --fixture bbb-4k-30-normal --profile 360p --profile 720p --duration-seconds 12 --output tools/media-player-stress/.artifacts/hls/remediation-check`
  and `uv run python tools/media-player-stress/build_hls_ladder.py --fixture bbb-320x180-24 --profile 360p --profile 720p --duration-seconds 12 --output tools/media-player-stress/.artifacts/hls/remediation-low-v2`
  exercised the 4K/audio and low-resolution/audio paths, exact per-segment
  `CODECS`, MPEG-TS container checks, and the exact WebVTT
  `EXT-X-MEDIA`/caption playlist. (The output directories are ignored local
  artifacts.)
- `uv run python tools/media-player-stress/build_hls_ladder.py --fixture bbb-4k-30-normal --duration-seconds 12 --output tools/media-player-stress/.artifacts/hls/remediation-final-six-v3`
  exercised all six declared resolutions/bitrates (2160p, 1440p, 1080p, 720p,
  480p, and 360p). Every profile produced three 4-second MPEG-TS segments;
  every segment passed exact H.264/AAC dimensions, MIME codec strings,
  `CODECS`, PTS/DTS continuity, and rendition-boundary checks. The output
  manifest records
  `playlist_content_type=application/vnd.apple.mpegurl`,
  `segment_container=mpegts`, six aligned quality-switch timelines,
  `http_requests_performed=false`, `pts_boundary_validation=true`, and three
  1,024-byte inclusive range samples per profile.
- `uv run pytest -q tests/unit/media/test_stress_fixture_composition.py tests/unit/media/test_stress_fixture_manifests.py`
  passes the focused composition/registry tests, including production/local
  denial, matching opaque scope, typed provider/grant verifiers, exact
  cache/path, checksum, provenance, caption, FFmpeg allowlist, redirect, and
  network-manifest checks: `24 passed`.
- `uv run ruff check packages/python/ac_platform/media/stress_fixtures.py packages/python/ac_platform/application/settings.py packages/python/ac_platform/media/__init__.py tests/unit/media/test_stress_fixture_composition.py tests/unit/media/test_stress_fixture_manifests.py tools/media-player-stress/fixture_harness.py tools/media-player-stress/acquire_media_fixtures.py tools/media-player-stress/build_hls_ladder.py`
  passed.
- `uv run pytest -q tests/unit` passes the full unit suite: `854 passed`, with
  one existing Starlette/httpx deprecation warning; focused fixture tests pass
  separately at `24 passed`.
- `uv run mypy packages/python` reports `Success: no issues found in 123
  source files`.
- `uv run ruff check` and `uv run ruff format --check` pass on the changed
  Python implementation and test files.
- `pnpm exec prettier --check apps packages/typescript package.json
  pnpm-workspace.yaml .github/workflows/application.yml` passes for the
  repository's application/configuration surfaces. (The evidence document
  retains the repository's existing prose formatting.)
- `git diff --check` passed. Invalid CLI timeout values now return bounded
  harness errors (exit code 2) without a traceback. Automatic redirects are
  disabled; every `Location` is validated against the exact HTTPS host/path
  allowlist before the request is rejected, so no redirect target is
  contacted. No push, deployment, production provider contact, or Playwright
  run was performed.

## Remaining activation requirements

This evidence does not close any activation gate. Before real staging or
production media can be used, the owning slice must still provide and record:

1. AC-GOV-AUD-001 approval for the provider/store/recording/AI data boundary,
   with consent, retention, provenance, and deletion policy evidence.
2. The open media gaps (including `GAP-MEDIA-001`) resolved by controlled docs,
   with an immutable externally attested activation verifier; no in-process
   flag or fixture manifest can substitute for that approval.
3. Approved private object storage, scanner, transcoder, callback inbox and
   asynchronous processing, signed HTTPS delivery, range/CORS policy, and
   backup/restore/retention evidence.
4. Server-side tenant/learning-scope authorization that issues a real
   version-bound playback grant. Fixture composition must remain downstream of
   that authorizer and must not grant access by asset id, URL, or fixture id.
5. QA/release evidence for captions, accessibility, failure/offline states,
   security deny paths, telemetry/audit separation, and exact staged runtime
   configuration. Manual VPS/DB state and analytics events cannot become
   authoritative.

Until those requirements are complete, this pipeline remains a local ignored
cache plus staging/test-only diagnostic seam and is not a production media
activation.
