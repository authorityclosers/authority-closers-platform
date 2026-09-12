# LearningLoopRuntime media-player stress harness

This development-only harness exercises the production `VideoViewer` with a
local, in-browser fake `LearnerApi`. It does not call the learner API, create a
playback grant, write progress/evidence, activate S3 or another provider, or
change auth policy. The synthetic trace is diagnostic evidence only.

## Media provenance

The public samples are Blender Foundation's Big Buck Bunny and Caminandes 2:
Gran Dillama, obtained from the official Blender download host:

- [Blender film/about page](https://peach.blender.org/about/)
- [Blender download page](https://peach.blender.org/download/)
- [Official 2160p 30fps normal download archive](https://download.blender.org/demo/movies/BBB/bbb_sunflower_2160p_30fps_normal.mp4.zip)
- [Official 320x180 download archive](https://download.blender.org/peach/bigbuckbunny_movies/BigBuckBunny_320x180.mp4.zip)
- [Caminandes 2 official film and current CC BY 4.0 license](https://studio.blender.org/projects/api/assets/2363/)
- [Caminandes 2 official 1080p archive](https://download.blender.org/demo/movies/caminandes_gran_dillama.mp4.zip)

Blender identifies Big Buck Bunny as Creative Commons Attribution 3.0 and the
current Caminandes 2 film item as Creative Commons Attribution 4.0. The exact
source URLs, license/provenance pages, retrieval date, archive hashes, and
extracted-file hashes are pinned in
[`fixture-manifest.json`](fixture-manifest.json). The three external fixtures are
test inputs only; they are not Authority Closers course content. Do not
substitute copyrighted course media. Keep the archive and extracted file under
the ignored `tools/media-player-stress/.artifacts/` directory. Use the
checksum-pinned acquisition CLI below; direct download, archive expansion, or
arbitrary public URLs are intentionally not part of this harness.

Preserve the original film credits and the manifest's attribution and license
links. Identify any excerpts, transcodes or synthetic caption tracks as test
derivatives; neither film is a Dipak recording or an Authority Closers lesson.

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
python tools/media-player-stress/acquire_media_fixtures.py acquire --fixture caminandes-gran-dillama-1080p
python tools/media-player-stress/acquire_media_fixtures.py generate --fixture generated-16x9-4s
python tools/media-player-stress/acquire_media_fixtures.py generate --fixture generated-4x3-6s
python tools/media-player-stress/acquire_media_fixtures.py generate --fixture generated-wide-3s
python tools/media-player-stress/acquire_media_fixtures.py verify
```

Render a bounded HLS ladder (the default is six declared resolutions/bitrates)
into a new ignored directory. Use a short duration for repeatable local smoke
checks; the source fixture itself remains pinned to its full metadata duration.
Renditions run sequentially, with each decoder, filter pipeline and encoder
limited to two FFmpeg worker threads. This is a per-pool bound, not a claim
that the entire process has only two threads; output/time/byte limits still
apply. The generated lavfi fixtures and their pinned commands are unchanged.

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

The complete 10m 34.6s official 2160p film has a separate release-pack command.
It leaves the short smoke pack unchanged, copies the verified H.264 2160p video
without re-encoding, normalizes the primary stereo track to AAC, and prepares a
source-keyframe-aligned 720p rendition. The command is local-only, limited to two
transcode threads and a bounded total timeout. The resulting progressive MP4,
adaptive HLS and checksummed `release-manifest.json` stay under the ignored
artifact cache:

```powershell
python -u tools/media-player-stress/prepare_full_film_release.py `
  --output tools/media-player-stress/.artifacts/full-film/bbb-4k-30-normal `
  --timeout-seconds 3600
```

This pack preserves the complete visual-frame inventory. It does not create a
course binding or waive the Studio upload-size, malware-scanning, publication,
tenant-access or playback-grant requirements.

The application seam is fail-closed: `AC_MEDIA_STRESS_FIXTURES_ENABLED` is
accepted only in test/development/staging, production rejects it, and fixture
composition requires an already-verified provider activation and playback grant
plus a checksummed local path below the ignored cache. This harness never
creates either gate. See
[`MEDIA_STRESS_FIXTURES_IMPLEMENTATION_EVIDENCE.md`](../../docs/evidence/MEDIA_STRESS_FIXTURES_IMPLEMENTATION_EVIDENCE.md)
for activation requirements and evidence boundaries.
