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
- [Official 320x180 download archive](https://download.blender.org/peach/bigbuckbunny_movies/BigBuckBunny_320x180.mp4.zip)

Blender identifies the film as Creative Commons Attribution 3.0. The checked
archive SHA-256 is
`109E3EDE8790BD633F374CA311D9CC61DCE8D7F98F5B0797CA98199C9FBCEEDF`; the
extracted MP4 SHA-256 is
`F78F39603E6774907F2FAAFABF26A667F4A6FC31769EC304A8A8F7C62D280508`.
Do not substitute copyrighted course media. Keep the archive and extracted
file under the ignored `.artifacts/media-player/` directory.

To fetch that exact archive into the ignored artifact directory:

```powershell
$mediaArtifactRoot = New-Item -ItemType Directory -Force .artifacts/media-player/official-bbb
Invoke-WebRequest `
  -Uri https://download.blender.org/peach/bigbuckbunny_movies/BigBuckBunny_320x180.mp4.zip `
  -OutFile .artifacts/media-player/BigBuckBunny_320x180.mp4.zip
Expand-Archive -LiteralPath .artifacts/media-player/BigBuckBunny_320x180.mp4.zip `
  -DestinationPath $mediaArtifactRoot -Force
```

The other fixtures are local FFmpeg test-pattern MP4s used only to cover
16:9/4:3/2.35:1 geometry and 3/4/6-second durations:

| Fixture | Dimensions | Duration | SHA-256 |
| --- | ---: | ---: | --- |
| `tiny-16x9-320x180-4s.mp4` | 320×180 | 4s | `DCC6D7B02BDFEA645631A82A59273A70F68D8041B745AA3934493D48C6E36A2E` |
| `tiny-4x3-320x240-6s.mp4` | 320×240 | 6s | `F3607EDACB69D96D4C85443F83AFC9E797B081B64200210750615F07ED9D2ACA` |
| `tiny-235x-640x272-3s.mp4` | 640×272 | 3s | `39B2AAD2064527CCAA91ED6B06A1855FD40075531B9C8BE41DDEE4F976AB8478` |

Regenerate local fixtures with an installed FFmpeg test source (never with
course content), for example:

```powershell
ffmpeg -f lavfi -i testsrc2=size=320x180:rate=30 -t 4 -an -c:v libx264 -pix_fmt yuv420p -movflags +faststart .artifacts/media-player/tiny-16x9-320x180-4s.mp4
```

Adjust `size`, `rate`, and `-t` for the remaining rows, then verify dimensions,
duration, and hashes with `ffprobe` and `Get-FileHash`.

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
are written only under ignored `.artifacts/media-player/`.

Provider-backed staging proof remains gated: real signed media delivery,
provider policy/consent/retention/provenance checks, and production auth/tenant
isolation still require the controlled staging gates and must not be inferred
from this fake-API run.
