# Deepgram native tail repair evidence

## Scope

This change starts from core commit `6cb09046b59811cafb482fccb8cd87ef9d7e5c8f` and
addresses the accepted Deepgram native transcript shape where C1 measures
`duration_ms=60000` and a final native segment ends at `60135`.

C2 remains the immutable provider-normalized artifact, including its native
timestamps, response revision, native timebase, and unverified provenance. A
detached playback projection is created only for provider-native clocks when a
segment end is within the existing `1000 ms` normalizer tolerance. It clamps the
playback end to C1's measured duration and records the native and projected
bounds in `ac.sales-xray.transcript-playback-projection/1`. Larger drift and a
tail-only segment that cannot retain positive playback bounds fail closed.

The projection flows through C3 alignment, C4 fact input, C5 coaching input,
durable C6 draft validation, retained C5 recovery, and owner transcript reads.
C3 continues to report the provider clock as unmapped to AudioAtlas, with no
speaker-channel attribution, measurement, score, or certified clock mapping.

## Validation on 2026-09-16

- Unit alignment, inference-task, and report tests: **63 passed**.
- Disposable loopback PostgreSQL proof on port `55439`, database
  `ac_local_sandbox`: the exact 60,000/60,135 ms Deepgram fixture advanced
  C2 → C3 → C4 → C5 and passed owner report/transcript reads: **1 passed**.
- Existing reporting-pipeline PostgreSQL suite: **4 passed**.
- Existing retained C5 PostgreSQL recovery proof: **1 passed**.
- Ruff, mypy, compileall, and `git diff --check`: **passed**.

The PostgreSQL proof used only the repository's synthetic broker. It made no
provider calls, deployment changes, or production database writes. The source
worktree remains isolated on `codex/sales-xray-native-tail-repair-20260916`.
