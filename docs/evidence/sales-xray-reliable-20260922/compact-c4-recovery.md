# Compact C4 recovery

The real hour-long staging call reached a retained C2 transcript, then its second
C4 request returned `MAX_TOKENS` at the approved 1,400-token output cap. The
response attempted a separate observation for nearly every turn. The provider
response, failed task, job receipt, and uncertain reservation remain retained.

## Implementation

New processing plans persist `facts-v2`. Its source-owned prompt selects bounded
observations about decisions, outcomes, pricing, authority, and limits. The
count and character limits scale with the existing approved output budget; at
1,400 tokens, each chunk allows eight observations. Validation rejects excess
output instead of silently truncating evidence. Exact source, chunk, quote,
and timestamp checks remain in force. C5 still receives the full transcript.

Legacy plans and requests default to `facts-v1`, and serialization omits that
default so their immutable fingerprints do not change. The new prompt changes
the request digest and fact cache key. A fresh plan can reuse its completed C2
checkpoint and request revised C4 work without rewriting the earlier failed
task. No provider limit, approval identity, or cost ceiling changes here.

## Verification before release

- Conversation unit suite before the final five boundary cases: **1,146 passed,
  one POSIX-only skip**. Final focused inference, Gemini, and processing-plan
  suites including those boundary cases: **95 passed**.
- CI-scoped Ruff checks and formatting passed for `packages/python tests`;
  mypy passed for **302 source files**. A broader exploratory Ruff invocation
  also visited unrelated web scripts, infrastructure, and historical migrations;
  it found existing issues outside the application CI scope. Those files were
  not changed by this repair.
- Actual retained C4 input hashes remain exactly `f6c1de0e...` and
  `bfcf5b33...` under v1. V2 produces distinct hashes for the same five transcript
  chunks. The retained `MAX_TOKENS` response still fails validation.
- Independent read-only review found no P1/P2 defect in compatibility,
  revision authorization, evidence bounds, caching, or failed-task preservation.
- PostgreSQL upgrade, processing-plan, Gemini-plan, and reporting suites:
  **23 passed**. The new paid-cost synthetic regression keeps one completed C2,
  holds legacy C4 on `MAX_TOKENS`, completes revised C4/C5 and the report, and
  preserves the old task, job receipt, command fingerprint, and uncertain minute
  and budget reservations. It uses one fact chunk; multi-chunk live acceptance
  remains separate. Historical plans are inserted in their original shape,
  with immutability guards enabled. The synthetic budget is established before
  processing; no recovery-time balance edit or provider network call occurs.
- Offline final-report capacity exercise with the actual transcript and
  synthetic capacity-only facts fits the existing approved C5 context and cost
  gate. This is not provider acceptance or generated-report quality evidence.

Exact-release CI is recorded when complete.
Live acceptance still requires all C4 chunks, C5, report review, cited playback,
saved-call reload, and restoration of the separately approved temporary C2
allowance. Production remains on the previous release.
