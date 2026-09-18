# Bounded video encode cost correction

The filesystem worker previously used libx264's default `medium` preset for
every HLS rendition and the full-resolution progressive output. On a worker
limited to one CPU, the latter can dominate processing time for a long 4K file.
Both existing encode commands now select `veryfast`. Codec, pixel format, thread
limits, duration/geometry handling, HLS bitrate targets, metadata removal,
private storage, scanning and publication gates are retained.

This is a compression/speed tradeoff, not a promise of identical encoded bytes
or quality. A bounded local comparison used the same first eight seconds of the
licensed 3840x2160, 30 fps test file, two encoder threads and the existing
progressive command. Exact source SHA-256:
`37f0ff251a606c2dcfa26c19fe6bf843234b4e7a8889cfab50bc26f644e55520`.

| Preset | Local elapsed | Encoded bytes | SSIM against source |
| --- | ---: | ---: | ---: |
| medium | 49.672 s | 3,882,290 | 0.998368 |
| veryfast | 19.281 s | 3,155,203 | 0.997207 |

Both outputs were probed as eight-second 3840x2160 H.264/yuv420p files. This small
sample is preliminary evidence, not representative of every scene or a forecast
for the one-CPU VPS. The retained original source allows later regeneration.

The changed processor passed all 41 targeted tests in 24.32 seconds with no
skips, including actual FFmpeg portrait, rotation, anamorphic, audio-tail,
low-frame-rate, private-file, rendition geometry and isolated-attempt checks.
Receipt: `D:/AC-authority-closers-release-audit/v02-media-preset-01.xml`.
Local timing and SSIM receipts are in
`D:/AC-authority-closers-release-audit/video-preset-20260913/`.

This patch is isolated for independent review and final release integration.
No running worker was changed and no source was uploaded or published by this
comparison. Full-file staging processing and mobile playback remain required.
