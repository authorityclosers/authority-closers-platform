# LearningLoopRuntime media-player stress harness

This development-only harness exercises the production `VideoViewer` with a
local, in-browser fake `LearnerApi`. It does not call the learner API, create a
playback grant, write progress/evidence, activate S3 or another provider, or
change auth policy. The synthetic trace is diagnostic evidence only.

## Media provenance

The public sample is Blender Foundation's Big Buck Bunny, obtained from the
official Blender download host:

- [Blender film/about page](https://peach.blender.org/about/)
- [Blender download page](https://peach.blender.org/download/)
- [Official 2160p 30fps normal download archive](https://download.blender.org/demo/movies/BBB/bbb_sunflower_2160p_30fps_normal.mp4.zip)
- [Official 320x180 download archive](https://download.blender.org/peach/bigbuckbunny_movies/BigBuckBunny_320x180.mp4.zip)

Blender identifies the film as Creative Commons Attribution 3.0. The exact
source URLs, license/provenance pages, retrieval date, archive hashes, and
extracted-file hashes are pinned in
[`fixture-manifest.json`](fixture-manifest.json). The two external fixtures are
test inputs only; they are not Authority Closers course content. Do not
substitute copyrighted course media. Keep the archive and extracted file under
the ignored `tools/media-player-stress/.artifacts/` directory. Use the
checksum-pinned acquisition CLI below; direct download, archive expansion, or
arbitrary public URLs are intentionally not part of this harness.

The other fixtures are local FFmpeg test-pattern MP4s used only to cover
16:9/4:3/2.35:1 geometry and 3/4/6-second durations:

| Fixture             | Dimensions | Duration | SHA-256                                                            |
| ------------------- | ---------: | -------: | ------------------------------------------------------------------ |
| `generated-16x9-4s` |    320×180 |       4s | `DCC6D7B02BDFEA645631A82A59273A70F68D8041B745AA3934493D48C6E36A2E` |
| `generated-4x3-6s`  |    320×240 |       6s | `E192F2962AEEF78EE4CB664A9B2136B691BDC6FA884C0AE279A624C68AEB532A` |
| `generated-wide-3s` |    640×272 |       3s | `39B2AAD2064527CCAA91ED6B06A1855FD40075531B9C8BE41DDEE4F976AB8478` |

Regenerate local fixtures with the checksum-pinned CLI and installed FFmpeg
test source (never with course content):

```powershell
python tools/media-player-stress/acquire_media_fixtures.py generate --fixture generated-16x9-4s
python tools/media-player-stress/acquire_media_fixtures.py generate --fixture generated-4x3-6s
python tools/media-player-stress/acquire_media_fixtures.py generate --fixture generated-wide-3s
```

The CLI verifies dimensions, duration, codecs, container, and pinned hashes;
it refuses a different FFmpeg version or a non-`testsrc2` source.

## Run

Use an isolated development port so an unrelated local app cannot be mistaken
for this route:

```powershell
python C:\Users\Suyash\.agents\skills\webapp-testing\scripts\with_server.py `
  --server "pnpm --filter @ac/learner-web exec next dev --turbopack --port 3030" `
  --port 3030 -- `
  python -u tools/media-player-stress/run_media_player_stress.py `
  --base-url http://localhost:3030
```

The script runs metadata/geometry, captions, transcript seeking, play/pause/
resume, playback rate, mute, keyboard focus, deterministic fullscreen
rejection, reduced-motion at 320px, and mobile 390px cases. It also exercises
an aborted heartbeat, expired grant reacquisition, expired playback-session
restart, and finish retry without a duplicate heartbeat. JSON and screenshots
are written only under ignored `tools/media-player-stress/.artifacts/`.

Provider-backed staging proof remains gated: real signed media delivery,
provider policy/consent/retention/provenance checks, and production auth/tenant
isolation still require the controlled staging gates and must not be inferred
from this fake-API run.

## Reproducible CLI fixture and HLS harness

The CLI below is independent of the browser harness and was the only stress
path used for this fixture work. It uses no Playwright, provider, database, or
public playback URL. It accepts only the exact HTTPS Blender archive paths
already listed in the manifest (443 or implicit 443), writes only below the
ignored artifact cache, and verifies SHA-256 before extraction or rendering.
Generated MP4 hashes are
pinned to the FFmpeg version prefix declared in the manifest; HLS output records
the exact installed FFmpeg version in its output manifest. `--cache-root` may
only select the ignored `tools/media-player-stress/.artifacts/` boundary or a
descendant; parent traversal, symlink/reparse escapes, and custom manifests are
rejected.

```powershell
python tools/media-player-stress/acquire_media_fixtures.py manifest
python tools/media-player-stress/acquire_media_fixtures.py acquire --fixture bbb-4k-30-normal
python tools/media-player-stress/acquire_media_fixtures.py acquire --fixture bbb-320x180-24
python tools/media-player-stress/acquire_media_fixtures.py generate --fixture generated-16x9-4s
python tools/media-player-stress/acquire_media_fixtures.py generate --fixture generated-4x3-6s
python tools/media-player-stress/acquire_media_fixtures.py generate --fixture generated-wide-3s
python tools/media-player-stress/acquire_media_fixtures.py verify
```

Render a bounded HLS ladder (the default is six declared resolutions/bitrates)
into a new ignored directory. Use a short duration for repeatable local smoke
checks; the source fixture itself remains pinned to its full metadata duration.

```powershell
python tools/media-player-stress/build_hls_ladder.py `
  --fixture bbb-4k-30-normal `
  --duration-seconds 12 `
  --output tools/media-player-stress/.artifacts/hls/bbb-4k-30-normal
```

Each output contains `master.m3u8`, one VOD playlist per rendition, hashed MPEG-
TS segments, synthetic WebVTT captions, and `hls-manifest.json` with the exact
FFmpeg version/arguments, corrected container/`CODECS` descriptors, and output
checksums. The manifest also records a local inclusive-byte-range simulation
and aligned segment-timeline quality-switch check; these are not HTTP/provider
delivery proof. The deterministic network-state
matrix and the test assertions are in
[`network-scenarios.json`](network-scenarios.json) and
[`test-manifest.json`](test-manifest.json). They describe local simulation
metadata only; they do not issue live network requests.

The application seam is fail-closed: `AC_MEDIA_STRESS_FIXTURES_ENABLED` is
accepted only in test/development/staging, production rejects it, and fixture
composition requires an already-verified provider activation and playback grant
plus a checksummed local path below the ignored cache. This harness never
creates either gate. See
[`MEDIA_STRESS_FIXTURES_IMPLEMENTATION_EVIDENCE.md`](../../docs/evidence/MEDIA_STRESS_FIXTURES_IMPLEMENTATION_EVIDENCE.md)
for activation requirements and evidence boundaries.
