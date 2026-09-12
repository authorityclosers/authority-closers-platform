# Sales Xray signal implementation evidence — 2026-09-13

This receipt is for the offline local signal lane. It does not certify provider
execution, staging, production, KVM4 load, speech validity or scientific scoring.
The coordinator owns domain/auth/migration integration and deployment.

## Implemented

- Exact AudioAtlas C++ source, original license and provenance preserved under
  `native/audioatlas`; source SHA256
  `40b8b05256986da5eb5d49c3b3cb48c52d511117ecf2e59d56849457cb12fae3`.
- Explicit build/verified executable, local input snapshot and hash, bounded
  probe/decode/native subprocesses, stable errors without media/stderr exposure,
  temporary cleanup at every pipeline stage, new immutable checkpoint directories.
- Streaming standard-library `.aaf` feature container (40-byte header, 66-byte
  rows) with integer sample/channel/support, float32 descriptors, missing-pitch
  and invalid/partial flags; exact row coverage/ordering and digest validation.
- Conservative source-bound decoded-clock fusion, verified stereo assignments,
  mixed-overlap abstention, full-window containment, valid-tail channel peak,
  decimated display and clear measurement limits.
- Actual recovered SignalLab source inspected without accessing datasets/media.
  Hash catalogue records core80ms/10ms, balanced80ms/40ms, research/forensic80ms/10ms,
  native-rate spectra versus16k pitch, absolute grid rounding and piecewise PTS
  source mapping. The distinct engine is not silently substituted or activated.

## Executed here

All paths below are under the external receipt directory:
`D:/Projects/authority-closers-release-transfer/2026-09-13-sales-xray/receipts`.

| Check | Actual result | Receipt |
| --- | --- | --- |
| Native MSVC C++17 `/O2` build | Exit0; executable ran successfully | `build-sales-xray-native.cmd`, `signals-native-build.json` |
| Signal suite final run | 52 passed, no skips, 3.07 seconds | `signals-junit.xml` |
| Ruff final scoped check | All checks passed | Command below; local tool result |
| Strict mypy scoped check | No issues in one source file | Command below; local tool result |
| 30s synthetic stereo complete pipeline | 1.297 seconds;6,000 rows;396,040 feature bytes | `profile-signals-synthetic.py`, `signals-synthetic-resource.json` |

Built executable SHA256:
`6f739c66ac316dcdba2eab747e00b09a95fa4db849399f34584cb175d325c452`.
The same binary was copied to the extracted original lab's ignored `build` directory
for the coordinator's separate original-package baseline; that baseline is not
claimed by this lane.

Commands, working directory `D:/Projects/authority-closers-platform-sales-xray`:

```powershell
$env:PYTHONPATH = 'D:/Projects/authority-closers-platform-sales-xray/packages/python'
& 'C:/Windows/System32/cmd.exe' /d /c 'D:/Projects/authority-closers-release-transfer/2026-09-13-sales-xray/receipts/build-sales-xray-native.cmd'
& 'D:/Projects/authority-closers-platform/.venv/Scripts/python.exe' -m pytest tests/unit/conversation_intelligence/test_signals.py -q --junitxml='D:/Projects/authority-closers-release-transfer/2026-09-13-sales-xray/receipts/signals-junit.xml'
& 'D:/Projects/authority-closers-platform/.venv/Scripts/python.exe' -m ruff check packages/python/ac_platform/conversation_intelligence/signals.py tests/unit/conversation_intelligence/test_signals.py
& 'D:/Projects/authority-closers-platform/.venv/Scripts/python.exe' -m mypy --follow-imports=silent packages/python/ac_platform/conversation_intelligence/signals.py
& 'D:/Projects/authority-closers-platform/.venv/Scripts/python.exe' 'D:/Projects/authority-closers-release-transfer/2026-09-13-sales-xray/receipts/profile-signals-synthetic.py'
```

The suite exercises seven tone frequencies, direct versus FFT autocorrelation at
8/16/48kHz, opposite-phase stereo, gain/dBFS invariance, NaN/Inf handling, tails,
bounded float32 error, corrupt source support/packed rows, deterministic packing,
clock/source mismatch, stereo verification, mixed overlap, child timeout/output/
file limits, excluded synthetic provider credentials, cleanup at five failure
stages, real synthetic WAV resampling and playlist rejection. Native numerical
tests would report explicit skips if the build were absent; this run had zero.

The full-process profile used Python3.12.0 on Windows11, 30 seconds of synthetic
48kHz signed16 stereo, opposite-phase200Hz tones, decoded at16kHz. No customer
recording was accessed by this specialist and no audio was sent externally.
GetProcessMemoryInfo measured peak working sets: parent25,182,208 bytes,
ffprobe21,217,280 bytes, ffmpeg22,958,080 bytes, AudioAtlas4,026,368 bytes.
Their sum73,383,936 bytes is a conservative sum of individual peaks, not concurrent
RSS or an enforced limit. Parent CPU/memory includes fixture generation. This
single local run does not establish KVM4 capacity or adversarial parser safety.

## Integration and remaining gates

`inspect_media(source, outdir, rate=16000, max_seconds=1800)` returns the complete
`ac.sales-xray.signal-checkpoint/1` JSON, including C1 identity, source/feature
digests, acoustics metadata, decoded/source-clock limitations and display arrays.
It has no provider dependency and no dependency change request. Native code needs
an explicit build/package step and ffmpeg/ffprobe in the dedicated worker image;
the ordinary Python wheel currently does not contain the native directory.

No customer upload API may directly expose file paths, compiler/native selection
or these local process helpers. Dedicated worker OS filesystem/network/memory/
process-tree confinement, private durable storage/deletion, exact recording
permission/retention provenance and provider approvals remain activation gates.
Bounded subprocess controls do not satisfy those gates by themselves. Source
container/video alignment and the actual SignalLab adapter remain unimplemented.
No ASR/VAD/speaker separation, coach scoring, retraining or numeric publication
is enabled here. This lane's provider-tested, staged and production-published
status is **not performed**; broader product status belongs to coordinator receipts.

## Additional private local storage transport

The coordinator subsequently assigned `conversation_intelligence/storage.py` and
`tests/unit/conversation_intelligence/test_storage.py`. No settings, database,
authorization, migrations or existing transport gates were changed by this lane.

`PrivateLocalRecordingStorage(root)` requires an explicit absolute root outside
Git repositories. It creates a private marked root, or reopens a previously marked
root; it refuses unrelated existing directories. `ObjectKey` contains typed server
UUIDs for tenant, recording and blob plus a fixed `ObjectKind` enum. No incoming
URL, user filename or caller-selected relative path becomes a storage key.

Windows creates a protected inheritable DACL for the current worker user, SYSTEM
and local administrators. Directory handles pin ancestors against rename/delete;
OPEN_REPARSE_POINT and attribute checks reject junctions/reparse points. POSIX
uses openat-style directory descriptors, O_NOFOLLOW, 0700 directories and0600
files; this platform branch has not been executed locally. Existing hard-linked
aliases are rejected on reads/deletes. These protections are not isolation from
the same Windows user, administrators or a compromised worker process.

`put` streams at most128 MiB, limits each bytes chunk to1 MiB, requires exact SHA256,
optionally checks expected byte count, flushes/fsyncs data, and publishes with an
atomic exclusive hard link. Existing objects are never replaced. Unpublished
temporary objects are removed after stream, checksum, size or publication failures.
There is no unsafe rename fallback on filesystems without hard-link support.
`iter_bytes` checks size and complete SHA before first yield; consumers must close
abandoned iterators. Private stored objects are immutable through this API.
Request/stream-generator timeouts, filesystem quotas, crash durability and writer
process isolation remain worker/runtime responsibilities.

`list_recording(tenant_id, recording_id)` inventories only that exact UUID scope
and fixed object kinds. It rejects unexpected files, in-flight upload temporaries,
reparse points and aliases. `delete_recording(..., expected_keys=tuple(...))`
compares actual inventory to database-owned expected keys, permits already-absent
objects for retries, rejects extra objects, deletes exact keys and re-enumerates.
The receipt explicitly records `local_inventory_empty=true` and
`domain_generation_fence_verified=false`. The domain must fence the generation
and drain writers before calling it; the filesystem adapter cannot establish
that fence. Empty namespace directories may remain. A local empty inventory does
not prove source deletion from user Downloads, backups or another provider.

For a worker, stream a verified source object into its private temporary workspace,
then call `inspect_media(source_path, workspace / "new-checkpoint")` with a fresh
nonexistent output directory. Store generated artifacts under separate server
blob IDs with their recorded hashes. Remove the worker materialization when the
operation finishes. Public clients never receive or control those filesystem paths.

Actual storage validation: **28 passed, zero skips,1.16 seconds**, including real
Windows DACL inspection, symlink/hard-link rejection, namespace non-aliasing,
checksum/size/chunk rejection, interrupted streams, publication cleanup, immutable
writes, bounded reads, idempotent delete, exact recording inventory, unexpected
in-flight files and a write-racing-deletion reproduction. Scoped Ruff passed;
strict mypy passed for `storage.py`. Machine JUnit: `storage-junit.xml` in the same
external receipt directory. Test run used Python3.12.0 on Windows11.

The first storage test run correctly refused this machine's default pytest temp
directory because `C:/Users/Suyash/.git` exists. The successful run used explicit
external `--basetemp`:

```powershell
$env:PYTHONPATH = 'D:/Projects/authority-closers-platform-sales-xray/packages/python'
& 'D:/Projects/authority-closers-platform/.venv/Scripts/python.exe' -m pytest tests/unit/conversation_intelligence/test_storage.py -q --tb=short --basetemp='D:/Projects/authority-closers-release-transfer/2026-09-13-sales-xray/receipts/storage-tests-temp' --junitxml='D:/Projects/authority-closers-release-transfer/2026-09-13-sales-xray/receipts/storage-junit.xml'
& 'D:/Projects/authority-closers-platform/.venv/Scripts/python.exe' -m ruff check packages/python/ac_platform/conversation_intelligence/storage.py tests/unit/conversation_intelligence/test_storage.py
& 'D:/Projects/authority-closers-platform/.venv/Scripts/python.exe' -m mypy --follow-imports=silent packages/python/ac_platform/conversation_intelligence/storage.py
```

This explicitly private local deployment transport is implemented and tested here.
It does not activate the current R2 adapter, public real-call storage, retention
policy, durable deletion jobs, external inference, staging or production. The
coordinator must report any later integration proof separately.

The subsequent isolated container-candidate assignment is documented in
`infra/conversation-worker/README.md`. It pins the official Python base digest,
builds the unchanged native source, and specifies effective Linux sandbox checks,
explicit resource/mount limits and no network.31 static/mocked checks and28 storage
regressions passed together in1.89seconds (zero skips), with machine receipt
`storage-sandbox-final-junit.xml`; final Ruff and strict Linux-target mypy for
signals/storage passed. No container build or runtime confinement proof was run
by this specialist. Conditional access to Windows-only APIs preserves platform
portability; source-native bytes remain unchanged.
