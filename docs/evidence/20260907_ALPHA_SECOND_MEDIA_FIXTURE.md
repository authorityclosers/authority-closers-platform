# Alpha second high-quality media fixture — 2026-09-07

## Result and boundary

Added the complete **Caminandes 2: Gran Dillama** film as the distinct 1080p
companion to the existing Big Buck Bunny 2160p fixture. Both are openly licensed
technical test inputs. Neither is a Dipak recording, an Authority Closers lesson,
or evidence that approved course playback has been activated.

The checked-in registry, CLI and application-side fixture registry retain
`test_only`, `course_content=false`, ignored-cache confinement, exact HTTPS
source/member/provenance allowlists, checksum verification, and the existing
provider-activation/playback-grant gates. Production remains rejected and
configuration remains disabled by default. No VPS, database, provider,
publication, binding, playback-grant or canonical learning state was changed.

## Primary source and license evidence

- [Official Blender source directory](https://download.blender.org/demo/movies/)
  lists `caminandes_gran_dillama.mp4.zip`, 125,632,282 bytes, dated 24-Nov-2023.
- [Exact source ZIP](https://download.blender.org/demo/movies/caminandes_gran_dillama.mp4.zip).
- [Official per-film Blender Studio item, asset 2363](https://studio.blender.org/projects/api/assets/2363/)
  identifies Caminandes 2: Gran Dillama, 1920×1080, 2:26, and explicitly links
  [Creative Commons Attribution 4.0](https://creativecommons.org/licenses/by/4.0/).
- [Official credits](https://studio.blender.org/projects/caminandes-2/pages/credits/)
  identify director Pablo Vazquez, producer Francesco Siddi, writer Beorn Leonard,
  and music/sound by Jan Morgenstern, alongside the remaining credited team.

License/version is taken from the current specific film item, inspected on
2026-09-07, not from a generic Blender footer or a third-party mirror. This does
not assert that the 2013 original release used version 4.0. The archive's full
film and credits are retained unchanged. Required presentation attribution is:

> Blender Foundation / Blender Studio; Caminandes 2: Gran Dillama (2013), directed by Pablo Vazquez; studio.blender.org

Keep this credit, the source link and license link with testing copies. Any
excerpts, transcodes or synthetic captions must be identified as test
derivatives, not original film subtitles, original lessons or an endorsement.

## Verified source record

| Field                    | Verified value                                                     |
| ------------------------ | ------------------------------------------------------------------ |
| Fixture ID               | `caminandes-gran-dillama-1080p`                                    |
| Archive bytes            | 125,632,282                                                        |
| Archive SHA-256          | `2e54abfb18dcb0a25d41e7b5d97fd51b226cec58d2fbcad101cf6deecea8c48b` |
| Exact sole ZIP member    | `caminandes_gran_dillama.mp4`                                      |
| Member bytes             | 125,974,946                                                        |
| Member SHA-256           | `468e6743c674689a728726bbe4bb4b2a65bd8702a89f021af26a8bb4d450eebd` |
| Native frame/codec       | 1920×1080, 24/1 fps, H.264 video, AAC audio, MP4                   |
| Full duration            | 146.041667 seconds; verification tolerance 0.25 seconds            |
| Fixture manifest SHA-256 | `fc61c87d5428d53d35b82061a53fbdbd9967b8bf658c6d0425a78a07bc106290` |
| Test manifest SHA-256    | `34fc19911d55ef0d002c19ca22dc15f31ca8e443fe8ae10e0fb32fdda0080411` |

The first enrollment streamed the exact official URL into its own ignored
source directory, refused redirects, validated Windows CA trust through
`truststore.inject_into_ssl()`, required the exact directory-listed
Content-Length, enforced the same observed byte ceiling and a ten-minute
deadline, validated the ZIP inventory/compression bounds, and hashed the
archive and member. Download completed in 12.59 seconds. No TLS verification
was disabled. The one-time enrollment helper remains an ignored local artifact;
it is not an application endpoint or an unpinned acquisition mode.

After establishing these pins, the normal checked-in `acquire` and `verify`
commands rechecked the archive and extracted member. `verify` passed using the
complete local file and its measured FFprobe metadata. Existing BBB bytes,
source records, and generated lavfi fixture hashes were not changed.

## Resource-bounded diagnostic HLS smoke

`build_hls_ladder.py` now sets decoder, simple-filter, complex-filter and
encoder worker pools to two threads each. Renditions were already sequential
and remain so. This is not a two-thread total-process or OS memory quota.
Existing duration, timeout, output-path, source-checksum and byte safeguards
remain in force. The separate generated-fixture FFmpeg argument lists and
their pinned hashes are unchanged.

This prevents automatic per-core transcode worker expansion on small shared
workstations. It does not claim that automatic FFmpeg threads were the sole
cause of the separately observed Windows resource-exhaustion error.

Real bounded smoke command:

```powershell
uv run python tools/media-player-stress/acquire_media_fixtures.py acquire --fixture caminandes-gran-dillama-1080p
uv run python tools/media-player-stress/acquire_media_fixtures.py verify --fixture caminandes-gran-dillama-1080p
uv run python tools/media-player-stress/build_hls_ladder.py --fixture caminandes-gran-dillama-1080p --duration-seconds 12 --profile 1080p --profile 360p --output tools/media-player-stress/.artifacts/hls/alpha-20260907-caminandes-12s-2threads
```

Output used FFmpeg `8.1.1-full_build-www.gyan.dev`, produced three four-second
segments per 1080p and 360p rendition, and passed the existing aligned-timeline,
CODECS, synthetic-caption and inclusive-byte-slice checks. No 4K upsampling
was claimed as source quality. Source remains the complete 1080p film; HLS
output is a twelve-second transcoded test excerpt.

Output manifest:
`tools/media-player-stress/.artifacts/hls/alpha-20260907-caminandes-12s-2threads/hls-manifest.json`

SHA-256: `5617ff3f9a3be138fdad8f7865a7395e39f100be70b99b7f2a25aee8baad2177`.

The output records `http_requests_performed=false` and
`transport=local_byte_slice_simulation`. This proves local packaging and
simulation only, **not** signed HTTP playback, deployed player behavior,
adaptive streaming or VPS/provider acceptance.

## Regression checks

- New and existing focused fixture suites: **34 passed**.
- All `tests/unit/media`: **161 passed**, one existing Starlette/httpx
  deprecation warning.
- Ruff format/check on the changed Python files: **passed**.
- Mypy on `packages/python/ac_platform/media/stress_fixtures.py`: **passed**.
- `git diff --check`: **passed**, repeated at handoff.
- Independent read-only review: **no Critical or Important findings**. Reviewer
  independently rehashed both manifest sidecars and the new source archive and
  member, and reran the 34 focused media checks successfully.

New tests verify two distinct native high-quality source records, synchronized
runtime/CLI manifest pins, exact source-to-license/provenance/member pairing,
runtime revalidation, and invoked FFmpeg worker options both with and without
audio. Existing composition tests continue to prove production rejection,
explicit opt-in and mandatory typed provider/grant authorization.

The manifest authority changed intentionally for the new source. Earlier BBB
HLS output bearing the previous manifest hash is historical diagnostic evidence;
it is not silently rewritten or promoted to current/live acceptance.
