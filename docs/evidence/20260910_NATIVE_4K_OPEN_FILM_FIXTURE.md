# Native 4K open-film fixture verification — 2026-09-10

## Accepted local source

The ignored media stress cache contains the complete official Blender Foundation
**Big Buck Bunny, Sunflower version — 2160p 30fps normal** film. It is a technical
test fixture, not canonical course content and not a publication or provider
activation.

- Canonical fixture id: `bbb-4k-30-normal`
- Source page: <https://peach.blender.org/about/>
- Official 4K download index: <https://download.blender.org/demo/movies/BBB/>
- Exact archive URL: <https://download.blender.org/demo/movies/BBB/bbb_sunflower_2160p_30fps_normal.mp4.zip>
- License: Creative Commons Attribution 3.0
- Attribution: `Blender Foundation 2008, Janus Bager Kristensen 2013; Big Buck Bunny, Sunflower version`
- Archive bytes: `632204510`
- Archive SHA-256: `750b255c6d9fee1e2a03a6716d4f358bca56e9115bf3e06a66162fc5272ae151`
- Extracted bytes: `633016449`
- Extracted SHA-256: `37f0ff251a606c2dcfa26c19fe6bf843234b4e7a8889cfab50bc26f644e55520`
- Probed video: H.264, `3840x2160`, `30/1` fps, `634.533333` seconds
- Probed container duration: `634.600000` seconds (10m 34.6s)
- Probed audio: MP3 160 kb/s and AC-3 320 kb/s
- Local ignored path: `tools/media-player-stress/.artifacts/sources/bbb-4k-30-normal/bbb_sunflower_2160p_30fps_normal.mp4`

The source and attribution record is already pinned in
`tools/media-player-stress/fixture-manifest.json`. The source is the full film,
not a loop, excerpt, padded file, or locally upscaled derivative. Because this is
CGI, the precise claim is an official Blender-distributed 2160p render, not a
camera-native acquisition. Do not describe its 10m 34.6s running time as a
20–60 minute lecture.

## Verification performed

The following read-only checks passed from the authoritative worktree:

```text
.venv/Scripts/python.exe tools/media-player-stress/acquire_media_fixtures.py acquire --fixture bbb-4k-30-normal --timeout-seconds 600
.venv/Scripts/python.exe tools/media-player-stress/acquire_media_fixtures.py verify --fixture bbb-4k-30-normal
Get-FileHash -Algorithm SHA256 <archive>,<extracted-file>
ffprobe -v error -show_entries format=filename,format_name,duration,size,bit_rate:stream=index,codec_type,codec_name,width,height,r_frame_rate,avg_frame_rate,duration,bit_rate -of json <extracted-file>
```

The independent hashes matched the manifest exactly. `ffprobe` reported an MP4
container, a single 3840x2160 H.264 video stream and the two expected audio
streams. The binary cache remains excluded from Git by `.gitignore`.

## Honest longer-source candidate (not downloaded or enrolled)

NASA Scientific Visualization Studio item 12034 publishes **Thermonuclear Art:
The Sun in Ultra-High Definition** as a nominal 30-minute `3840x2160` download:

- Official page: <https://svs.gsfc.nasa.gov/12034/>
- Official metadata API: <https://svs.gsfc.nasa.gov/api/12034>
- Candidate file: <https://svs.gsfc.nasa.gov/vis/a010000/a012000/a012034/SDO_UHD_30mins_YouTube.mp4>
- Official listed size: `8.4 GB` (the exact byte count was not available from
  the metadata API and the media host was not reachable from the local shell)
- Official page classification: `3840x2160`; the page presents the 4K release
  as public domain
- Required credit: `The SDO Team, Genna Duberstein and Scott Wiessinger, Producers`
- Rights caveat: the page separately says all tracks were written and produced
  by Lars Leonhard. No right to reuse that third-party soundtrack is inferred
  from NASA's general media status.

This candidate was deliberately not downloaded. Its listed 8.4 GB size is far
above the current 100 MiB Studio source-upload cap and is at or above the fixture
manifest's 8 GiB extracted-file ceiling. It would also consume roughly one third
of the 24.4 GiB free on the local volume before processing outputs. A future
acquisition requires an explicit, reviewed larger-file policy and either
documented soundtrack permission or an approved audio-free derivative that does
not alter the visual duration or resolution. That future derivative must receive
its own digest and provenance record; it must not be presented as the untouched
NASA file.

## Capability boundary

This evidence proves source provenance and local byte integrity only. It does
not authorize upload, course binding, publication, access, playback, deployment,
or any change to the current Studio 100 MiB admission limit.
