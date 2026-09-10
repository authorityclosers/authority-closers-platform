# Video processing geometry and duration — local implementation

Date: 2026-09-09. Existing `codex/local-staging-dev-bridge` implementation tree.
These uncommitted worker changes are excluded from release candidate
`452ee2923b27edcec00da7816d699b162bf65450` and have not activated an upload provider.

## Implemented and verified

- Bounded local ffprobe inspection: selected video geometry, pixel aspect ratio,
  rotation and finite duration; 64 KiB per output stream and a 30-second process
  timeout. No network protocols, shell execution or surfaced media stderr.
- Aspect-correct, even-dimension H.264/yuv420p renditions without upscaling or
  duplicate tiers; source display geometry returned for ready-media metadata.
- Output geometry and duration verified from encoded bytes. Overbudget sources
  are rejected before encoding, not silently trimmed. Failed outputs are cleaned
  while the original remains preserved.
- Known worker-generated TS segments use explicit MPEG-TS probing so tiny/low-FPS
  clips are not rejected by container auto-detection.
- An audio tail is preserved by holding the last video frame, bounded to the
  measured source duration. Command helpers without a measured duration do not
  pad to the quota ceiling.

Validation on Windows, Python 3.12.0 and FFmpeg/ffprobe 8.1.1:
`pytest tests/unit/media tests/integration/test_ffmpeg_video_metadata.py -q`
passed **843 tests**, including seven real synthetic encodes: landscape, portrait,
rotation, anamorphic pixels, audio, longer audio tail and low frame rate. Real
outputs were re-probed and progressive output decoded; audio duration was checked.
Ruff passed. Mypy passed both production source files. Independent review found
two encode defects, reproduced their fixes, and reported no remaining Critical/
Important findings; its nonblocking helper-duration issue was also corrected.

One existing FastAPI/Starlette httpx deprecation warning remains. Real encode tests
skip explicitly if FFmpeg/ffprobe are absent; a skipped environment is not encoder
acceptance. The host still needs reviewed worker isolation: this probe is not a
malware scanner. No real course upload, content approval, provider activation,
staging or production playback is claimed by this evidence.

## Bounded long-source staging follow-up

FFmpeg source staging now streams chunks of at most 1 MiB into an exclusive
temporary file instead of buffering the entire source. The worker checks the
source quota and reserves its temporary-disk budget before staging, then verifies
the complete byte count, SHA-256 and unchanged storage metadata/revision before
decoding. MIME comparison preserves the service's existing case/parameter
normalization, and storage revisions retain the existing 255-character contract.
Partial temporary files and their budget reservation are cleaned on failure.

Validation progressed from 31 targeted source/metadata tests to 33 after the MIME
and revision compatibility corrections. The full media suite passed 862 tests,
including seven real FFmpeg encodes, before those two compatibility changes; the
final source-staging plus real-FFmpeg run passed 28 tests after the corrections.
Ruff and mypy passed, and independent re-review found no remaining Critical or
Important issues in this slice.

A checksum-pinned, single-entry `ReadOnlyFileMediaStorage` inventory staged the
actual 478,887,328-byte (456.703 MiB) local fixture in 1.388 seconds using 457
chunks, with a maximum chunk size of 1 MiB and peak traced Python allocation of
2.011 MiB. This measurement covers metadata checking and staging after storage
registration verified the original hash; it excludes imports, registration and
the independent chunked hash of the staged copy, and is not process RSS. Both
copies matched SHA-256
`6b5e36abc968ebe96f4e8ec82a41bff2d7d9924240a4b2bc0d96f64de36db5cc`.
The original remained unchanged and the isolated temporary copy was removed
automatically. Local-only measurement script and JSON are retained under
`.tmp/local-platform/new/long-video-streaming-20260909/`
(`verify_streaming.py`, `evidence.json`).

The prepared 52m53s, 720p repeated Big Buck Bunny fixture is CC BY 3.0 technical
test material only—not a native 4K lecture or Dipak instructional content. This
check performed no encoding, upload, course binding, database or runtime writes.
Normal upload/provider enablement and live course playback remain unclaimed.
These changes are also excluded from installer release
`7bdd069d4bf00561edcab90b1679666205708185`.
