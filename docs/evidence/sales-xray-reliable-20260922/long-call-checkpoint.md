# Sixty-minute support checkpoint

This supersedes the duration/resource assumptions in the earlier recovery
checkpoints. It does not claim that a live, complex hour-long conversation has
passed transcription or report-quality acceptance.

## Authorized scope

The owner explicitly requested complex calls up to 60 minutes and approved a
total INR 1,000 recovery-testing ceiling. Production remains unchanged. The
previous exact production renewal for `819a3b10` has not been issued or activated.
Any changed release and processing limits must have matching approval evidence.

## Fixes and boundaries

- A 3,600-second MP3 probes as 3,600.072 seconds with the deployed FFprobe 5.1
  decoder. Provisional metadata now allows at most one second of codec padding;
  decoded samples must still fit exactly 3,600 seconds.
- Native feature rows were capped at 360,000 total, accidentally limiting stereo
  to about 30 minutes. The total cap is now 720,000 for two physical channels.
- A one-hour stereo decode exceeds the old 256 MiB per-file limit and 512 MiB
  temporary workspace. The confined runtime now has a 512 MiB file bound, 768 MiB
  workspace and 1 GiB memory with no swap. Network isolation, read-only root,
  unprivileged user, capability drop, seccomp, process/CPU limits and timeouts
  remain enforced. The public source limit remains 32 MiB; native 128 MiB bounds
  do not imply public support for that size.
- New structured Gemini Flash coaching requests with more than 4,000 output
  tokens can carry 256,000 total conservative units. Every UTF-8 input byte,
  canonical response-schema byte, wrapper allowance and output token is counted.
  Both quote admission and broker dispatch independently require the pinned paid
  pricing reference/hash and sufficient per-request cost before using context
  beyond the previous 96,000-unit ceiling. Maximum 8,000-token output at this
  envelope has a conservative INR 21.60 ceiling at the pinned rates. Legacy v1
  request bytes retain their original 48,000/96,000 limits.

## Local evidence

Frozen source was bound read-only into the verified `819a` native image for an
isolated resource experiment with real FFmpeg and AudioAtlas. No provider or
database was called. The input was stereo synthetic tones, not speech.

- Input: 28,800,909 bytes, 3,600,000 ms, two channels.
- Input SHA-256: `72cd16647bde0c452125213f357b9446f7dafe951abd191e204fa5d8f9bd4539`.
- Frozen signals SHA-256: `a7f43826d28a3dc18d49cbb54bff5710684225a4a5fb016379669debd56707fb`.
- Runtime program SHA-256: `ee61a67d54f226406dc97b2ca3cd776aa2769ef8725cf59bbea6264450c48ce0`.
- Result: exit 0, 120.968 seconds, 720,000 rows, 47,520,040 feature bytes.
- Feature SHA-256: `97ce0e61f9901f5bfb73b8f923eb174e6f62d930bf8ed28e1c9876257c1d6e2a`.

Focused prompt/authority/plan checks: 146 unit tests and 22 PostgreSQL integration
tests passed. Native focused checks: 105 passed, one Windows/POSIX ownership skip.
An independent review reproduced 32 long-context/dispatch tests and found no
P1/P2 issue. Full Python Ruff formatting/lint and mypy passed. The combined unit
run initially found one fixture still sized for the old 96k rejection boundary;
that rejection fixture now exceeds 256k and its 13-test module passes.
The final combined conversation unit run passed 1,124 tests with the same single
Windows/POSIX ownership skip.

## Remaining acceptance

The live staging approval still permits only 30-minute sources and a 3,200-token
C5 output. Its INR 100 release cap is separate from the existing INR 10,000
shared ledger cap. A new, append-only provider revision and exact release approval
must precede a long live test. Neither a larger ledger nor this code checkpoint
changes those permissions.

Required next evidence: frozen-release CI and deployment, a genuine long fictional
conversation with measured speech turns, complete C4 coverage, source-bound facts
from the beginning/middle/end, correct late decision, report citations, playback,
reload and bounded recovery. A successful resource run alone cannot establish
report quality or reliability for arbitrary user recordings.
