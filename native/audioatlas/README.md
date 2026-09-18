# AudioAtlas native source and Sales Xray adapter

The original `atlas_dsp.cpp` is preserved byte for byte at SHA256
`40b8b05256986da5eb5d49c3b3cb48c52d511117ecf2e59d56849457cb12fae3`.
`LICENSE` and `source_provenance.json` are copied from the supplied Conversation
Lab package without edits. Local attributes disable line-ending normalization
for these original files. No binary, model weights, recording, or dependency is
included in source control.

The Python adapter is
`packages/python/ac_platform/conversation_intelligence/signals.py`.
It uses the Python standard library for streaming, deterministic feature packing.
Its public worker entry is:

```python
from pathlib import Path
from ac_platform.conversation_intelligence.signals import inspect_media

checkpoint = inspect_media(
    Path("/private/approved-local-input.wav"),
    Path("/private/new-checkpoint-directory"),
    rate=16000,
)
```

The output directory must not exist. The parent must be private and worker-owned;
never expose source/output paths or executable selection as public request fields.
The operation snapshots and hashes the exact bytes used for decoding, then removes
that temporary snapshot, decoded PCM and legacy rows on every success/failure.
Only `features.aaf` and `checkpoint.json` remain after success. A profile/judge
revision may reuse this C1 checkpoint and the independent C2 transcript.

Build explicitly in an operator build environment. `inspect_media` never compiles:

```python
from ac_platform.conversation_intelligence.signals import build_native
build_native()
```

The helper accepts an optional output directory and explicit compiler path. It
supports C++17 `g++`, `clang++`, or MSVC `cl` with the normal MSVC build environment
already activated. The source hash and binary hash are verified at execution.
The local build manifest detects accidental mismatch; it is not a signed supply
chain attestation. Packaged workers must ship the source/license and exact binary
manifest together; a Python wheel alone does not currently bundle this native tree.

## Binary feature contract

Little-endian, uncompressed, deterministic format `ac.audioatlas.features/1`.
This replaces the reference's numpy NPZ container; it does not claim NPZ compatibility.
The decoder is `iter_features(path)` and validates layout, coverage, rows and flags.

Header, struct `<8sIIQIIQ`, 40 bytes:

| Field | Storage |
| --- | --- |
| Magic `ACAAF001` | 8 bytes |
| Decoded rate, physical channels | uint32 each |
| Samples per channel | uint64 |
| Window samples, hop samples | uint32 each |
| Total rows across channels | uint64 |

Rows, struct `<IBHHB14f`, 66 bytes:

| Field | Storage |
| --- | --- |
| Window start sample | uint32 |
| Physical channel | uint8 |
| Valid samples, invalid-input count | uint16 each |
| Flags | uint8 |
| Descriptors | 14 float32 values |

Descriptor order: RMS, RMS dBFS, sample peak, possible clipping fraction, DC offset,
zero-cross rate, spectral centroid Hz, bandwidth Hz, 85% rolloff Hz, flatness,
entropy, spectral flux, F0 candidate Hz, YIN-style periodicity. Missing F0 is a
NaN in binary and null in JSON. Other nonfinite descriptors are rejected.
Flags: 1 partial window, 2 invalid input samples, 4 missing pitch. Native input
NaN/Inf and values above the legacy kernel's magnitude threshold are counted;
their affected frames cannot support attribution. Rows are frame-major/channel-minor.

Only 16kHz and 48kHz inspection profiles are enabled, with native 40ms windows and
10ms hops. Full support is `[start_sample, start_sample + valid_samples)`.
This is 100 starts/second/channel, not independent 10ms spectral precision.
Physical channels never automatically become speakers. Fusion requires the same
source hash and decoded-track clock, verified stereo assignments, full support
inside the transcript span, and abstention on mixed-channel overlap. Channel peak
can include finite partial tails; pitch/attribution cannot use partial tails.

## Different clocks and profiles

`SIGNALLAB_COMPATIBILITY.json` records inspected, hashed SignalLab source files,
including Studio v0.2 settings/configuration and both recovered audio engines.
SignalLab's core uses 80ms windows; balanced uses 40ms hops and research/forensic
use 10ms hops. It measures spectra at native rate, pitch on a separate 16kHz
derivative, and rounds each absolute sample-grid position. Its source map is
piecewise decoded-frame PTS, validated against native decoded sample counts.
These are not equivalent to the preserved AudioAtlas engine or its join policy.
No SignalLab extractor or certified interchange adapter is activated here.

The checkpoint records source rate, source track origin and timebase, decoded
rate/sample count, nominal sample ratio, derivative transformations, and the
explicit status `uncertified_codec_delay_origin_and_discontinuities`. A nonzero
track origin does not certify a constant offset. No source/video synchronization
claim follows from the local decode. Transcripts on another clock are rejected
until an independently validated conversion is supplied upstream.

## Limits and release boundary

Input <=128 MiB, duration <=3600s, <=2 physical channels, <=360,000 feature rows.
The hosted 16 kHz profile therefore supports one hour; the offline 48 kHz
profile remains bounded by the same row ceiling and may reject longer sources.
FFprobe has a 20s timeout; decoding has 90s and its own duration/byte/thread caps;
native extraction has 600s and exact expected output size. The subprocess wrapper
caps stdout, discards stderr, kills/reaps timed-out children, and passes only a
small tool/build environment allowlist. Protocol and demuxer allowlists exclude
network and playlist demuxers. Decoder/native errors are stable sanitized codes.

These controls are not an OS sandbox. Filesystem escape, decoder vulnerabilities,
process-tree/memory hard limits and network isolation need a dedicated constrained
worker before untrusted public uploads. Watchdog output checks can observe bytes
after they are written; they are defense in depth, not a disk quota. Windows
temporary directories inherit the worker's ACL; `mode=0700` is not a Windows ACL
policy. No native package, ffmpeg build or commercial/provider approval is inferred
from the original MIT notice. No neural VAD, diarization, transcription, calibrated
voice/emotion detection, deep-window extractor, or scientific scoring is shipped
by this adapter.
